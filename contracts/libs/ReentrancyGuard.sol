// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title ReentrancyGuard - protects functions against reentrancy attacks
abstract contract ReentrancyGuard {
    uint256 private constant _NOT_ENTERED = 1;
    uint256 private constant _ENTERED = 2;

    uint256 private _status;

    error Reentrancy();

    constructor() {
        _status = _NOT_ENTERED;
    }

    modifier nonReentrant() {
        if (_status == _ENTERED) {
            revert Reentrancy();
        }
        _status = _ENTERED;
        _;
        _status = _NOT_ENTERED;
    }
}
