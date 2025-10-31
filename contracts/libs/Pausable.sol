// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "./Ownable.sol";

/// @title Pausable
/// @notice Simple pausability mixin for emergency stops.
abstract contract Pausable is Ownable {
    event Paused(address indexed account);
    event Unpaused(address indexed account);

    bool private _paused;

    modifier whenNotPaused() {
        require(!_paused, "Paused");
        _;
    }

    modifier whenPaused() {
        require(_paused, "NotPaused");
        _;
    }

    function paused() public view returns (bool) {
        return _paused;
    }

    function pause() external onlyOwner whenNotPaused {
        _paused = true;
        emit Paused(msg.sender);
    }

    function unpause() external onlyOwner whenPaused {
        _paused = false;
        emit Unpaused(msg.sender);
    }
}
