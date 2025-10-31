// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract MockBitcoinRelayer {
    address public lastRecipient;
    uint256 public lastAmount;
    bytes public lastParams;

    function releaseToBitcoin(address recipient, uint256 amount, bytes calldata params) external {
        lastRecipient = recipient;
        lastAmount = amount;
        lastParams = params;
    }
}
