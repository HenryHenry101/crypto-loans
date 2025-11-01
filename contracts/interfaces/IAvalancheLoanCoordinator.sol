// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IAvalancheLoanCoordinator {
    function initiateWithdrawal(bytes32 loanId, address btcRecipient, bytes calldata bridgeParams) external;

    function liquidate(bytes32 loanId, address payoutRecipient, bytes calldata unwindParams) external;
}
