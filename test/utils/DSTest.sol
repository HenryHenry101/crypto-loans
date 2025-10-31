// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract DSTest {
    event log(string message);
    event log_uint(string message, uint256 value);
    event log_address(string message, address value);
    event log_bytes32(string message, bytes32 value);

    function fail(string memory message) internal pure {
        revert(message);
    }

    function assertTrue(bool condition, string memory message) internal pure {
        if (!condition) {
            revert(message);
        }
    }

    function assertEq(uint256 a, uint256 b, string memory message) internal pure {
        if (a != b) {
            revert(message);
        }
    }

    function assertEq(address a, address b, string memory message) internal pure {
        if (a != b) {
            revert(message);
        }
    }

    function assertEq(bytes32 a, bytes32 b, string memory message) internal pure {
        if (a != b) {
            revert(message);
        }
    }
}
