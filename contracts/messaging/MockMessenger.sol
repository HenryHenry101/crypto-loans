// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "../libs/Ownable.sol";
import {ICrossChainMessenger} from "../interfaces/ICrossChainMessenger.sol";

/// @title MockMessenger
/// @notice Simplified messenger to simulate cross-chain payload delivery for development.
contract MockMessenger is Ownable, ICrossChainMessenger {
    event MessageQueued(uint256 indexed id, bytes payload, bytes params);
    event MessageDelivered(uint256 indexed id, address target);

    struct Message {
        address sender;
        bytes payload;
        bytes params;
        bool delivered;
    }

    Message[] public outbound;

    function sendMessage(bytes calldata payload) external payable override {
        outbound.push(Message({
            sender: msg.sender,
            payload: payload,
            params: "",
            delivered: false
        }));
        emit MessageQueued(outbound.length - 1, payload, "");
    }

    function deliver(uint256 messageId, address target, bytes calldata params) external onlyOwner {
        Message storage message = outbound[messageId];
        require(!message.delivered, "Already delivered");
        message.delivered = true;
        message.params = params;
        (bool ok,) = target.call(abi.encodeWithSignature("handleMessengerPayload(bytes,bytes)", message.payload, params));
        require(ok, "Delivery failed");
        emit MessageDelivered(messageId, target);
    }
}
