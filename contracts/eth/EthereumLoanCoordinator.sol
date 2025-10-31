// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "../libs/Ownable.sol";
import {ReentrancyGuard} from "../libs/ReentrancyGuard.sol";
import {SafeERC20, IERC20} from "../libs/SafeERC20.sol";
import {ICrossChainMessenger} from "../interfaces/ICrossChainMessenger.sol";
import {IPriceOracle} from "../interfaces/IPriceOracle.sol";

/// @title EthereumLoanCoordinator
/// @notice Manages fiat loans denominated in EURe and communicates with Avalanche collateral manager.
contract EthereumLoanCoordinator is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    enum LoanStatus { None, Active, Repaid, Defaulted }

    struct Loan {
        address user;
        uint256 collateralBTCb;
        uint256 principalEUR;
        uint256 repaymentDue;
        uint256 deadline;
        LoanStatus status;
    }

    event LoanRegistered(bytes32 indexed loanId, address indexed user, uint256 collateralBTCb, uint256 principalEUR, uint256 deadline);
    event LoanFunded(bytes32 indexed loanId, address indexed beneficiary, uint256 amountEURe);
    event RepaymentRecorded(bytes32 indexed loanId, uint256 amountEURe, bool viaMonerium);
    event LoanDefaulted(bytes32 indexed loanId);
    event CollateralReleaseRequested(bytes32 indexed loanId, address indexed btcRecipient);

    error UnknownLoan();
    error InvalidStatus();
    error InvalidAmount();

    uint256 public constant COMMISSION_BPS = 100; // 1%

    IERC20 public immutable eureToken;
    ICrossChainMessenger public messenger;
    IPriceOracle public priceOracle;
    address public avalancheCoordinator;

    mapping(bytes32 => Loan) public loans;
    mapping(address => address) public moneriumWalletForUser;
    mapping(address => bytes32[]) public userLoans;

    modifier onlyAvalanche() {
        require(msg.sender == avalancheCoordinator, "NotAvalanche");
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
        avalancheCoordinator = avalancheCoordinator_;
    }

    function setMoneriumWallet(address user, address eureWallet) external onlyOwner {
        moneriumWalletForUser[user] = eureWallet;
    }

    function registerLoan(
        bytes32 loanId,
        address user,
        uint256 collateralBTCb,
        uint256 principalEUR,
        uint256 duration
    ) external onlyAvalanche {
        if (loans[loanId].status != LoanStatus.None) revert InvalidStatus();
        uint256 deadline = block.timestamp + duration;
        loans[loanId] = Loan({
            user: user,
            collateralBTCb: collateralBTCb,
            principalEUR: principalEUR,
            repaymentDue: (principalEUR * (10000 + COMMISSION_BPS)) / 10000,
            deadline: deadline,
            status: LoanStatus.Active
        });
        userLoans[user].push(loanId);
        emit LoanRegistered(loanId, user, collateralBTCb, principalEUR, deadline);
    }

    function fundLoan(bytes32 loanId, address beneficiary) external onlyOwner {
        Loan storage loan = loans[loanId];
        if (loan.status != LoanStatus.Active) revert InvalidStatus();
        address payout = beneficiary;
        if (payout == address(0)) {
            payout = moneriumWalletForUser[loan.user];
        }
        require(payout != address(0), "No payout target");
        eureToken.safeTransfer(payout, loan.principalEUR);
        emit LoanFunded(loanId, payout, loan.principalEUR);
    }

    function recordRepayment(bytes32 loanId, uint256 amountEURe, address payer, bool viaMonerium)
        external
        nonReentrant
    {
        Loan storage loan = loans[loanId];
        if (loan.status != LoanStatus.Active) revert InvalidStatus();
        if (amountEURe < loan.repaymentDue) revert InvalidAmount();

        eureToken.safeTransferFrom(payer, address(this), amountEURe);
        loan.status = LoanStatus.Repaid;

        bytes memory payload = abi.encode("REPAYMENT_CONFIRMED", loanId, loan.user, amountEURe, payer);
        messenger.sendMessage(payload);
        emit RepaymentRecorded(loanId, amountEURe, viaMonerium);
        emit CollateralReleaseRequested(loanId, loan.user);
    }

    function flagDefault(bytes32 loanId) external onlyOwner {
        Loan storage loan = loans[loanId];
        if (loan.status != LoanStatus.Active) revert InvalidStatus();
        loan.status = LoanStatus.Defaulted;
        bytes memory payload = abi.encode("LOAN_DEFAULT", loanId, loan.user, loan.collateralBTCb, loan.repaymentDue);
        messenger.sendMessage(payload);
        emit LoanDefaulted(loanId);
    }

    function rescueEURe(address to, uint256 amount) external onlyOwner {
        eureToken.safeTransfer(to, amount);
    }
}
