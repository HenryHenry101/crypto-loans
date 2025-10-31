// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract MockAvalancheBridge {
    bool public valid = true;
    address public lastUser;
    uint256 public lastAmount;
    bytes public lastProof;

    function setValid(bool value) external {
        valid = value;
    }

    function validateProof(address user, uint256 amount, bytes calldata proof) external returns (bool) {
        lastUser = user;
        lastAmount = amount;
        lastProof = proof;
        return valid;
    }
}
