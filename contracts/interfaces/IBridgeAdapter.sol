// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IBridgeAdapter {
    function bridgeToBitcoin(address user, uint256 amount, bytes calldata bridgeParams) external;

    function unwindToStable(address beneficiary, uint256 amount, bytes calldata swapParams) external;
}
