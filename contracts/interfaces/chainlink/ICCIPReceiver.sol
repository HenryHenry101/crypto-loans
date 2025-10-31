// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ICCIPRouter} from "./ICCIPRouter.sol";

interface ICCIPReceiver {
    struct Any2EVMMessage {
        bytes32 messageId;
        uint64 sourceChainSelector;
        bytes sender;
        bytes data;
        ICCIPRouter.EVMTokenAmount[] destTokenAmounts;
    }
}
