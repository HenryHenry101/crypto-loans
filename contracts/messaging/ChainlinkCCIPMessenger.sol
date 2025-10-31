// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "../libs/Ownable.sol";
import {SafeERC20, IERC20} from "../libs/SafeERC20.sol";
import {ICrossChainMessenger} from "../interfaces/ICrossChainMessenger.sol";
import {ICCIPRouter} from "../interfaces/chainlink/ICCIPRouter.sol";
import {ICCIPReceiver} from "../interfaces/chainlink/ICCIPReceiver.sol";

/// @title ChainlinkCCIPMessenger
/// @notice Minimal CCIP adapter that relays payloads between Avalanche and Ethereum coordinators.
contract ChainlinkCCIPMessenger is ICrossChainMessenger, Ownable {
    using SafeERC20 for IERC20;

    error RouterNotSet();
    error TargetNotSet();
    error ReceiverNotConfigured();
    error UnauthorizedRouter();
    error UnknownSender();
    error FeePaymentFailed();

    event RouterUpdated(address indexed router);
    event DestinationUpdated(uint64 indexed selector, bytes receiver);
    event TargetUpdated(address indexed target);
    event TrustedRemoteUpdated(uint64 indexed selector, bytes sender);
    event ExtraArgsUpdated(bytes data);
    event FeeTokenUpdated(address token);
    event MessageSent(bytes32 indexed messageId, uint64 indexed destinationChainSelector, bytes payload);
    event MessageReceived(bytes32 indexed messageId, uint64 indexed sourceChainSelector, bytes sender, bytes payload);
    event FeesWithdrawn(address indexed token, uint256 amount, address indexed to);

    ICCIPRouter public router;
    uint64 public destinationChainSelector;
    bytes public remoteReceiver;
    address public target;
    address public feeToken;
    bytes public extraArgs;

    mapping(uint64 => bytes) public trustedRemotes;

    constructor(address owner_) {
        if (owner_ != address(0)) {
            _transferOwnership(owner_);
        }
    }

    receive() external payable {}

    function setRouter(address router_) external onlyOwner {
        router = ICCIPRouter(router_);
        emit RouterUpdated(router_);
    }

    function setDestination(uint64 selector, bytes calldata receiver_) external onlyOwner {
        destinationChainSelector = selector;
        remoteReceiver = receiver_;
        emit DestinationUpdated(selector, receiver_);
    }

    function setTarget(address target_) external onlyOwner {
        target = target_;
        emit TargetUpdated(target_);
    }

    function setTrustedRemote(uint64 selector, bytes calldata sender) external onlyOwner {
        trustedRemotes[selector] = sender;
        emit TrustedRemoteUpdated(selector, sender);
    }

    function setExtraArgs(bytes calldata extraArgs_) external onlyOwner {
        extraArgs = extraArgs_;
        emit ExtraArgsUpdated(extraArgs_);
    }

    function setFeeToken(address token) external onlyOwner {
        feeToken = token;
        emit FeeTokenUpdated(token);
    }

    function sendMessage(bytes calldata payload) external payable override {
        if (address(router) == address(0)) revert RouterNotSet();
        if (remoteReceiver.length == 0 || destinationChainSelector == 0) revert ReceiverNotConfigured();

        ICCIPRouter.EVMTokenAmount[] memory tokens = new ICCIPRouter.EVMTokenAmount[](0);
        ICCIPRouter.EVM2AnyMessage memory message = ICCIPRouter.EVM2AnyMessage({
            receiver: remoteReceiver,
            data: payload,
            tokenAmounts: tokens,
            feeToken: feeToken,
            extraArgs: extraArgs
        });

        uint256 fee = router.getFee(destinationChainSelector, message);
        bytes32 messageId;

        if (feeToken == address(0)) {
            if (msg.value < fee) revert FeePaymentFailed();
            messageId = router.ccipSend{value: fee}(destinationChainSelector, message);
            if (msg.value > fee) {
                (bool refunded,) = payable(msg.sender).call{value: msg.value - fee}("");
                require(refunded, "RefundFailed");
            }
        } else {
            IERC20(feeToken).safeApprove(address(router), 0);
            IERC20(feeToken).safeApprove(address(router), fee);
            messageId = router.ccipSend(destinationChainSelector, message);
        }

        emit MessageSent(messageId, destinationChainSelector, payload);
    }

    function ccipReceive(ICCIPReceiver.Any2EVMMessage calldata message) external {
        if (msg.sender != address(router)) revert UnauthorizedRouter();
        bytes memory expectedSender = trustedRemotes[message.sourceChainSelector];
        if (expectedSender.length == 0 || keccak256(expectedSender) != keccak256(message.sender)) {
            revert UnknownSender();
        }
        if (target == address(0)) revert TargetNotSet();

        emit MessageReceived(message.messageId, message.sourceChainSelector, message.sender, message.data);

        (bool success,) = target.call(
            abi.encodeWithSignature(
                "handleMessengerPayload(bytes,bytes)",
                message.data,
                abi.encode(message.sourceChainSelector, message.sender, message.messageId)
            )
        );
        require(success, "TargetCallFailed");
    }

    function withdrawNative(address payable to, uint256 amount) external onlyOwner {
        (bool ok,) = to.call{value: amount}("");
        require(ok, "NativeTransferFailed");
        emit FeesWithdrawn(address(0), amount, to);
    }

    function rescueToken(address token, address to, uint256 amount) external onlyOwner {
        IERC20(token).safeTransfer(to, amount);
        emit FeesWithdrawn(token, amount, to);
    }
}
