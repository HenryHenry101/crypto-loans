// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Pausable} from "../libs/Pausable.sol";
import {ReentrancyGuard} from "../libs/ReentrancyGuard.sol";
import {SafeERC20, IERC20} from "../libs/SafeERC20.sol";
import {ICrossChainMessenger} from "../interfaces/ICrossChainMessenger.sol";
import {IPriceOracle} from "../interfaces/IPriceOracle.sol";
import {IAvalancheLoanCoordinator} from "../interfaces/IAvalancheLoanCoordinator.sol";

/// @title EthereumLoanCoordinator
/// @notice Manages fiat loans denominated in EURe and communicates with Avalanche collateral manager.
contract EthereumLoanCoordinator is Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    enum LoanStatus {
        None,
        Active,
        Repaid,
        Defaulted
    }

    struct Loan {
        address user;
        uint256 collateralBTCb;
        uint256 principalEUR;
        uint256 repaymentDue;
        uint256 deadline;
        uint256 ltvBps;
        uint256 createdAt;
        LoanStatus status;
        bool fundsDisbursed;
        bytes32 bridgeProofHash;
        bytes32 lastMessageId;
    }

    event LoanRegistered(
        bytes32 indexed loanId,
        address indexed user,
        uint256 collateralBTCb,
        uint256 principalEUR,
        uint256 deadline
    );
    event LoanFunded(bytes32 indexed loanId, address indexed beneficiary, uint256 amountEURe);
    event RepaymentRecorded(bytes32 indexed loanId, uint256 amountEURe, bool viaMonerium);
    event LoanDefaulted(bytes32 indexed loanId);
    event CollateralReleaseRequested(bytes32 indexed loanId, address indexed btcRecipient, bytes bridgeParams);
    event LoanMetadataSynced(bytes32 indexed loanId, uint256 ltvBps, uint256 createdAt, bytes32 bridgeProofHash);
    event OperatorStatusChanged(address indexed operator, bool enabled);

    error UnknownLoan();
    error InvalidStatus();
    error InvalidAmount();
    error NotMessenger();
    error UnauthorizedOperator();
    error UnknownAction();
    error OracleStale();
    error ExcessivePrincipal();

    uint256 public constant COMMISSION_BPS = 100; // 1%
    uint256 public constant MAX_LTV_BPS = 7000;
    uint256 public constant ORACLE_TIMEOUT = 1 hours;

    IERC20 public immutable eureToken;
    ICrossChainMessenger public messenger;
    IPriceOracle public priceOracle;
    IAvalancheLoanCoordinator public avalancheCoordinator;

    mapping(bytes32 => Loan) public loans;
    mapping(address => address) public moneriumWalletForUser;
    mapping(address => bytes32[]) public userLoans;
    mapping(address => bool) public authorizedOperators;

    modifier onlyAvalanche() {
        require(msg.sender == address(avalancheCoordinator), "NotAvalanche");
        _;
    }

    modifier onlyMessenger() {
        if (msg.sender != address(messenger)) revert NotMessenger();
        _;
    }

    constructor(address eureToken_, address messenger_, address priceOracle_) {
        require(eureToken_ != address(0), "TokenZero");
        eureToken = IERC20(eureToken_);
        messenger = ICrossChainMessenger(messenger_);
        priceOracle = IPriceOracle(priceOracle_);
    }

    function setMessenger(address messenger_) external onlyOwner {
        messenger = ICrossChainMessenger(messenger_);
    }

    function setAvalancheCoordinator(address avalancheCoordinator_) external onlyOwner {
        avalancheCoordinator = IAvalancheLoanCoordinator(avalancheCoordinator_);
    }

    function setMoneriumWallet(address user, address eureWallet) external onlyOwner {
        moneriumWalletForUser[user] = eureWallet;
    }

    function setAuthorizedOperator(address operator, bool enabled) external onlyOwner {
        authorizedOperators[operator] = enabled;
        emit OperatorStatusChanged(operator, enabled);
    }

    function registerLoan(
        bytes32 loanId,
        address user,
        uint256 collateralBTCb,
        uint256 principalEUR,
        uint256 duration
    ) external onlyAvalanche {
        _registerLoan(loanId, user, collateralBTCb, principalEUR, duration, 0, block.timestamp, bytes32(0), bytes32(0));
    }

    function handleMessengerPayload(bytes calldata payload, bytes calldata params) external nonReentrant whenNotPaused onlyMessenger {
        (uint64 selector, bytes memory sender, bytes32 messageId) = abi.decode(params, (uint64, bytes, bytes32));
        selector; sender; // reserved for audit logs / allowlists
        (
            string memory action,
            bytes32 loanId,
            address user,
            uint256 collateralBTCb,
            uint256 principalEUR,
            uint256 ltvBps,
            uint256 duration,
            uint256 createdAt,
            bytes memory bridgeProof
        ) = abi.decode(payload, (string, bytes32, address, uint256, uint256, uint256, uint256, uint256, bytes));

        bytes32 actionHash = keccak256(bytes(action));
        if (actionHash == keccak256(bytes("LOAN_CREATED"))) {
            _registerLoan(loanId, user, collateralBTCb, principalEUR, duration, ltvBps, createdAt, keccak256(bridgeProof), messageId);
        } else {
            revert UnknownAction();
        }
    }

    function fundLoan(bytes32 loanId, address beneficiary) external onlyOwner whenNotPaused {
        Loan storage loan = loans[loanId];
        if (loan.status != LoanStatus.Active) revert InvalidStatus();
        if (loan.fundsDisbursed) revert InvalidStatus();
        address payout = beneficiary;
        if (payout == address(0)) {
            payout = moneriumWalletForUser[loan.user];
        }
        require(payout != address(0), "No payout target");
        eureToken.safeTransfer(payout, loan.principalEUR);
        loan.fundsDisbursed = true;
        emit LoanFunded(loanId, payout, loan.principalEUR);
    }

    function recordRepayment(
        bytes32 loanId,
        uint256 amountEURe,
        address payer,
        bool viaMonerium,
        bytes calldata bridgeParams
    ) external nonReentrant whenNotPaused {
        Loan storage loan = loans[loanId];
        if (loan.status != LoanStatus.Active) revert InvalidStatus();
        if (amountEURe < loan.repaymentDue) revert InvalidAmount();
        if (msg.sender != payer && !authorizedOperators[msg.sender]) revert UnauthorizedOperator();

        eureToken.safeTransferFrom(payer, address(this), amountEURe);
        loan.status = LoanStatus.Repaid;

        bytes memory payload = abi.encode("REPAYMENT_CONFIRMED", loanId, loan.user, amountEURe, bridgeParams);
        if (address(avalancheCoordinator) != address(0)) {
            avalancheCoordinator.initiateWithdrawal(loanId, loan.user, bridgeParams);
        } else {
            messenger.sendMessage(payload);
        }
        emit RepaymentRecorded(loanId, amountEURe, viaMonerium);
        emit CollateralReleaseRequested(loanId, loan.user, bridgeParams);
    }

    function flagDefault(bytes32 loanId, bytes calldata unwindParams) external onlyOwner whenNotPaused {
        Loan storage loan = loans[loanId];
        if (loan.status != LoanStatus.Active) revert InvalidStatus();
        loan.status = LoanStatus.Defaulted;
        bytes memory payload = abi.encode("LOAN_DEFAULT", loanId, loan.user, loan.collateralBTCb, unwindParams);
        if (address(avalancheCoordinator) != address(0)) {
            avalancheCoordinator.liquidate(loanId, loan.user, unwindParams);
        } else {
            messenger.sendMessage(payload);
        }
        emit LoanDefaulted(loanId);
    }

    function rescueEURe(address to, uint256 amount) external onlyOwner {
        eureToken.safeTransfer(to, amount);
    }

    function _registerLoan(
        bytes32 loanId,
        address user,
        uint256 collateralBTCb,
        uint256 principalEUR,
        uint256 duration,
        uint256 ltvBps,
        uint256 createdAt,
        bytes32 bridgeProofHash,
        bytes32 messageId
    ) internal whenNotPaused {
        Loan storage loan = loans[loanId];
        if (loan.status != LoanStatus.None) revert InvalidStatus();
        if (ltvBps > MAX_LTV_BPS) revert InvalidAmount();
        if (ltvBps > 0) {
            if (block.timestamp - priceOracle.lastUpdate() > ORACLE_TIMEOUT) revert OracleStale();
            uint256 price = priceOracle.btcEurPrice();
            uint256 maxPrincipal = (collateralBTCb * price * ltvBps) / 1e18 / 10000;
            if (principalEUR > maxPrincipal) revert ExcessivePrincipal();
        }
        uint256 deadline = block.timestamp + duration;
        if (createdAt != 0 && createdAt + duration > block.timestamp) {
            deadline = createdAt + duration;
        }
        loans[loanId] = Loan({
            user: user,
            collateralBTCb: collateralBTCb,
            principalEUR: principalEUR,
            repaymentDue: (principalEUR * (10000 + COMMISSION_BPS)) / 10000,
            deadline: deadline,
            ltvBps: ltvBps,
            createdAt: createdAt == 0 ? block.timestamp : createdAt,
            status: LoanStatus.Active,
            fundsDisbursed: false,
            bridgeProofHash: bridgeProofHash,
            lastMessageId: messageId
        });
        userLoans[user].push(loanId);
        emit LoanRegistered(loanId, user, collateralBTCb, principalEUR, deadline);
        emit LoanMetadataSynced(loanId, ltvBps, createdAt, bridgeProofHash);
    }
}
