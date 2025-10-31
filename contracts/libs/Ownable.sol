// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title Ownable - simplified ownership access control
/// @notice Minimal Ownable implementation to avoid external dependencies.
abstract contract Ownable {
    address private _owner;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    error NotOwner();

    constructor() {
        _transferOwnership(msg.sender);
    }

    modifier onlyOwner() {
        if (msg.sender != _owner) {
            revert NotOwner();
        }
        _;
    }

    function owner() public view returns (address) {
        return _owner;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "OwnerZero");
        _transferOwnership(newOwner);
    }

    function renounceOwnership() external onlyOwner {
        _transferOwnership(address(0));
    }

    function _transferOwnership(address newOwner) internal {
        address previousOwner = _owner;
        _owner = newOwner;
        emit OwnershipTransferred(previousOwner, newOwner);
    }
}
