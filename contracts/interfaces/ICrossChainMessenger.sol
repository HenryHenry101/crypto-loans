// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface ICrossChainMessenger {
    function sendMessage(bytes calldata payload) external payable;
}
