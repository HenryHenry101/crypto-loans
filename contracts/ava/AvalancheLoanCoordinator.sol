// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Pausable} from "../libs/Pausable.sol";
import {ReentrancyGuard} from "../libs/ReentrancyGuard.sol";
import {SafeERC20, IERC20} from "../libs/SafeERC20.sol";
import {ISiloVault} from "../interfaces/ISiloVault.sol";
import {ICrossChainMessenger} from "../interfaces/ICrossChainMessenger.sol";
import {IPriceOracle} from "../interfaces/IPriceOracle.sol";
import {IBridgeAdapter} from "../interfaces/IBridgeAdapter.sol";
import {OwnershipToken} from "./OwnershipToken.sol";

/// @title AvalancheLoanCoordinator
/// @notice Handles BTC.b collateral lifecycle and cross-chain coordination with Ethereum loan manager.
contract AvalancheLoanCoordinator is Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    enum LoanState {
        None,
        Active,
        AwaitingUnlock,
        Releasing,
        Defaulted,
        Released
    }

    struct Position {
        address user;
        uint256 collateralAmount;
        uint256 vaultShares;
        uint256 loanPrincipalEUR;
        uint256 mintedTokens;
        uint256 ltvBps;
        uint64 createdAt;
        uint64 deadline;
        bytes32 bridgeProofHash;
        LoanState state;
    }

    event CollateralDeposited(
        bytes32 indexed loanId,
        address indexed user,
        uint256 amountBTCb,
        uint256 principalEUR,
        uint256 ltvBps,
        uint64 deadline
    );
    event OwnershipLocked(bytes32 indexed loanId, address indexed user);
    event CollateralReleased(bytes32 indexed loanId, address indexed user, uint256 amountBTCb);
    event LiquidationTriggered(bytes32 indexed loanId, address indexed user, uint256 amountBTCb);
    event BridgeProofVerified(bytes32 indexed loanId, bytes32 proofHash);

    error InvalidAmount();
    error InvalidState();
    error OracleStale();
    error NotLoanOwner();
    error VaultShareMismatch();
    error InvalidBridgeProof();

    uint256 public constant MAX_LTV_BPS = 7000; // 70%
    uint256 public constant ORACLE_TIMEOUT = 1 hours;

    IERC20 public immutable btcBToken;
    ISiloVault public immutable siloVault;
    ICrossChainMessenger public messenger;
    IBridgeAdapter public bridgeAdapter;
    OwnershipToken public immutable ownershipToken;
    IPriceOracle public priceOracle;

    mapping(bytes32 => Position) public positions;
    mapping(address => bytes32[]) public userLoans;

    uint64 private _loanCounter;
    address public ethereumLoanManager;

    constructor(
        address btcBToken_,
        address siloVault_,
        address priceOracle_,
        address messenger_,
        address bridgeAdapter_
    ) {
        require(btcBToken_ != address(0) && siloVault_ != address(0), "AddrZero");
        btcBToken = IERC20(btcBToken_);
        siloVault = ISiloVault(siloVault_);
        priceOracle = IPriceOracle(priceOracle_);
        messenger = ICrossChainMessenger(messenger_);
        bridgeAdapter = IBridgeAdapter(bridgeAdapter_);
        ownershipToken = new OwnershipToken("BTC Loan Receipt", "BTCREC", 18);
    }

    function setMessenger(address messenger_) external onlyOwner {
        messenger = ICrossChainMessenger(messenger_);
    }

    function setBridgeAdapter(address adapter_) external onlyOwner {
        bridgeAdapter = IBridgeAdapter(adapter_);
    }

    function setEthereumLoanManager(address manager_) external onlyOwner {
        ethereumLoanManager = manager_;
    }

    function setPriceOracle(address oracle_) external onlyOwner {
        priceOracle = IPriceOracle(oracle_);
    }

    function depositCollateral(
        uint256 amountBTCb,
        uint256 ltvBps,
        uint64 duration,
        bytes calldata bridgeProof
    ) external nonReentrant whenNotPaused returns (bytes32 loanId, uint256 principalEUR) {
        if (amountBTCb == 0) revert InvalidAmount();
        if (ltvBps == 0 || ltvBps > MAX_LTV_BPS) revert InvalidAmount();
        if (duration == 0) revert InvalidAmount();
        _ensureOracleFresh();

        bool proofValid = bridgeAdapter.validateBridgeProof(msg.sender, amountBTCb, bridgeProof);
        if (!proofValid) revert InvalidBridgeProof();

        btcBToken.safeTransferFrom(msg.sender, address(this), amountBTCb);

        btcBToken.safeApprove(address(siloVault), amountBTCb);
        uint256 sharesMinted = siloVault.deposit(amountBTCb);
        require(sharesMinted > 0, "Silo deposit failed");

        loanId = _nextLoanId();
        principalEUR = _calculatePrincipal(amountBTCb, ltvBps);
        uint256 mintedTokens = amountBTCb;

        positions[loanId] = Position({
            user: msg.sender,
            collateralAmount: amountBTCb,
            vaultShares: sharesMinted,
            loanPrincipalEUR: principalEUR,
            mintedTokens: mintedTokens,
            ltvBps: ltvBps,
            createdAt: uint64(block.timestamp),
            deadline: uint64(block.timestamp + duration),
            bridgeProofHash: keccak256(bridgeProof),
            state: LoanState.Active
        });

        userLoans[msg.sender].push(loanId);

        ownershipToken.mint(msg.sender, mintedTokens);

        bytes memory payload = abi.encode(
            "LOAN_CREATED",
            loanId,
            msg.sender,
            amountBTCb,
            principalEUR,
            ltvBps,
            duration,
            block.timestamp,
            bridgeProof
        );
        messenger.sendMessage(payload);

        emit BridgeProofVerified(loanId, keccak256(bridgeProof));
        emit CollateralDeposited(loanId, msg.sender, amountBTCb, principalEUR, ltvBps, positions[loanId].deadline);
    }

    function lockOwnershipToken(bytes32 loanId) external whenNotPaused {
        Position storage position = positions[loanId];
        if (position.state != LoanState.Active && position.state != LoanState.AwaitingUnlock) revert InvalidState();
        if (position.user != msg.sender) revert NotLoanOwner();

        ownershipToken.transferFrom(msg.sender, address(this), position.mintedTokens);
        position.state = LoanState.AwaitingUnlock;
        emit OwnershipLocked(loanId, msg.sender);
    }

    function handleMessengerPayload(bytes calldata payload, bytes calldata params) external nonReentrant {
        require(msg.sender == address(messenger), "NotMessenger");
        params; // silence unused warning - params reserved for future validation

        (string memory action, bytes32 loanId, address recipient, uint256 amount, bytes memory extraData) =
            abi.decode(payload, (string, bytes32, address, uint256, bytes));

        bytes32 actionHash = keccak256(bytes(action));
        if (actionHash == keccak256(bytes("REPAYMENT_CONFIRMED"))) {
            _processRepayment(loanId, recipient, extraData);
        } else if (actionHash == keccak256(bytes("LOAN_DEFAULT"))) {
            _processDefault(loanId, recipient, amount, extraData);
        } else if (actionHash == keccak256(bytes("UPDATE_MANAGER"))) {
            ethereumLoanManager = recipient;
        } else {
            revert("UnknownAction");
        }
    }

    function emergencyWithdraw(address token, address to, uint256 amount) external onlyOwner {
        IERC20(token).safeTransfer(to, amount);
    }

    function _processRepayment(bytes32 loanId, address btcRecipient, bytes memory bridgeParams) internal {
        Position storage position = positions[loanId];
        if (position.state != LoanState.AwaitingUnlock) revert InvalidState();

        uint256 sharesBurned = siloVault.withdrawShares(position.vaultShares);
        if (sharesBurned < position.collateralAmount) revert VaultShareMismatch();

        ownershipToken.burn(address(this), position.mintedTokens);
        position.state = LoanState.Releasing;

        btcBToken.safeApprove(address(bridgeAdapter), 0);
        btcBToken.safeApprove(address(bridgeAdapter), position.collateralAmount);
        bridgeAdapter.bridgeToBitcoin(btcRecipient, position.collateralAmount, bridgeParams);

        position.state = LoanState.Released;
        emit CollateralReleased(loanId, position.user, position.collateralAmount);
    }

    function _processDefault(bytes32 loanId, address payoutRecipient, uint256, bytes memory swapParams) internal {
        Position storage position = positions[loanId];
        if (position.state == LoanState.Defaulted || position.state == LoanState.Released) revert InvalidState();

        uint256 sharesBurned = siloVault.withdrawShares(position.vaultShares);
        if (sharesBurned < position.collateralAmount) revert VaultShareMismatch();

        position.state = LoanState.Defaulted;
        ownershipToken.burn(position.user, position.mintedTokens);

        btcBToken.safeApprove(address(bridgeAdapter), 0);
        btcBToken.safeApprove(address(bridgeAdapter), position.collateralAmount);
        bridgeAdapter.unwindToStable(payoutRecipient, position.collateralAmount, swapParams);

        emit LiquidationTriggered(loanId, position.user, position.collateralAmount);
    }

    function _nextLoanId() internal returns (bytes32 loanId) {
        loanId = keccak256(abi.encodePacked(address(this), ++_loanCounter, block.chainid));
    }

    function _calculatePrincipal(uint256 amountBTCb, uint256 ltvBps) internal view returns (uint256) {
        uint256 price = priceOracle.btcEurPrice();
        return (amountBTCb * price * ltvBps) / 1e18 / 10000;
    }

    function _ensureOracleFresh() internal view {
        if (block.timestamp - priceOracle.lastUpdate() > ORACLE_TIMEOUT) {
            revert OracleStale();
        }
    }
}
