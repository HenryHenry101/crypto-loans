// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract MockBridgeAdapter {
    address public lastRecipient;
    uint256 public lastAmount;
    bytes public lastParams;
    bool public unwindCalled;

    function bridgeToBitcoin(address user, uint256 amount, bytes calldata bridgeParams) external {
        lastRecipient = user;
        lastAmount = amount;
        lastParams = bridgeParams;
    }

    function unwindToStable(address beneficiary, uint256 amount, bytes calldata swapParams) external {
        lastRecipient = beneficiary;
        lastAmount = amount;
        lastParams = swapParams;
        unwindCalled = true;
    }
}
