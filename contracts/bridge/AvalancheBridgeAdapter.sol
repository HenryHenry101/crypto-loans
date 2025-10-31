// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "../libs/Ownable.sol";
import {ReentrancyGuard} from "../libs/ReentrancyGuard.sol";
import {SafeERC20, IERC20} from "../libs/SafeERC20.sol";
import {IBridgeAdapter} from "../interfaces/IBridgeAdapter.sol";

/// @notice Minimal interface for the Avalanche Bridge proof verifier.
interface IAvalancheBridgeVerifier {
    function validateProof(address user, uint256 amount, bytes calldata proof) external returns (bool);
}

/// @notice Interface for the authorized relayer that releases native BTC to users.
interface IBitcoinRelayer {
    function releaseToBitcoin(address recipient, uint256 amount, bytes calldata params) external;
}

/// @notice Interface for the on-chain DEX used during liquidations.
interface IStableSwap {
    function swapExactInput(address tokenIn, address tokenOut, uint256 amountIn, bytes calldata data)
        external
        returns (uint256 amountOut);
}

/// @title AvalancheBridgeAdapter
/// @notice Orchestrates proof validation, BTC bridging and liquidation unwinds for BTC.b collateral.
contract AvalancheBridgeAdapter is Ownable, ReentrancyGuard, IBridgeAdapter {
    using SafeERC20 for IERC20;

    uint256 private constant BPS_DENOMINATOR = 10_000;

    struct SecurityLimits {
        uint256 maxBridgeAmount;
        uint256 maxSlippageBps;
    }

    event BridgeUpdated(address indexed bridge);
    event RelayerUpdated(address indexed relayer);
    event DexUpdated(address indexed dex);
    event LimitsUpdated(uint256 maxBridgeAmount, uint256 maxSlippageBps);
    event BridgeProofValidated(address indexed user, uint256 amount, bytes32 proofHash);
    event BridgedToBitcoin(address indexed user, uint256 amount);
    event UnwoundToStable(address indexed beneficiary, uint256 amountOut);

    error AddressZero();
    error BridgeNotConfigured();
    error RelayerNotConfigured();
    error DexNotConfigured();
    error AmountExceedsLimit(uint256 amount, uint256 limit);
    error SlippageBpsTooHigh();
    error MinAmountOutTooLow(uint256 provided, uint256 required);
    error SlippageExceeded(uint256 received, uint256 minAmountOut);

    IERC20 public immutable btcBToken;
    IERC20 public immutable stableToken;

    IAvalancheBridgeVerifier public bridge;
    IBitcoinRelayer public relayer;
    IStableSwap public dex;
    SecurityLimits public limits;

    constructor(
        address btcBToken_,
        address stableToken_,
        address bridge_,
        address relayer_,
        address dex_,
        uint256 maxBridgeAmount_,
        uint256 maxSlippageBps_,
        address owner_
    ) {
        if (
            btcBToken_ == address(0) || stableToken_ == address(0) || bridge_ == address(0) || relayer_ == address(0)
                || dex_ == address(0) || owner_ == address(0)
        ) {
            revert AddressZero();
        }
        if (maxSlippageBps_ > BPS_DENOMINATOR) {
            revert SlippageBpsTooHigh();
        }

        btcBToken = IERC20(btcBToken_);
        stableToken = IERC20(stableToken_);
        bridge = IAvalancheBridgeVerifier(bridge_);
        relayer = IBitcoinRelayer(relayer_);
        dex = IStableSwap(dex_);
        limits = SecurityLimits({maxBridgeAmount: maxBridgeAmount_, maxSlippageBps: maxSlippageBps_});
        _transferOwnership(owner_);
    }

    function validateBridgeProof(address user, uint256 amount, bytes calldata bridgeProof)
        external
        override
        returns (bool)
    {
        _enforceAmount(amount);
        if (address(bridge) == address(0)) {
            revert BridgeNotConfigured();
        }

        bool valid = bridge.validateProof(user, amount, bridgeProof);
        if (valid) {
            emit BridgeProofValidated(user, amount, keccak256(bridgeProof));
        }
        return valid;
    }

    function bridgeToBitcoin(address user, uint256 amount, bytes calldata bridgeParams)
        external
        override
        nonReentrant
    {
        _enforceAmount(amount);
        if (address(relayer) == address(0)) {
            revert RelayerNotConfigured();
        }

        btcBToken.safeTransferFrom(msg.sender, address(this), amount);
        btcBToken.safeTransfer(address(relayer), amount);

        relayer.releaseToBitcoin(user, amount, bridgeParams);

        emit BridgedToBitcoin(user, amount);
    }

    function unwindToStable(address beneficiary, uint256 amount, bytes calldata swapParams)
        external
        override
        nonReentrant
    {
        _enforceAmount(amount);
        if (address(dex) == address(0)) {
            revert DexNotConfigured();
        }

        (uint256 minAmountOut, bytes memory dexData) = abi.decode(swapParams, (uint256, bytes));
        uint256 requiredMinOut = _requiredMinOut(amount);
        if (limits.maxSlippageBps != 0 && minAmountOut < requiredMinOut) {
            revert MinAmountOutTooLow(minAmountOut, requiredMinOut);
        }

        btcBToken.safeTransferFrom(msg.sender, address(this), amount);
        btcBToken.safeApprove(address(dex), 0);
        btcBToken.safeApprove(address(dex), amount);

        uint256 amountOut = dex.swapExactInput(address(btcBToken), address(stableToken), amount, dexData);
        if (amountOut < minAmountOut) {
            revert SlippageExceeded(amountOut, minAmountOut);
        }

        stableToken.safeTransfer(beneficiary, amountOut);

        emit UnwoundToStable(beneficiary, amountOut);
    }

    function updateBridge(address bridge_) external onlyOwner {
        if (bridge_ == address(0)) {
            revert AddressZero();
        }
        bridge = IAvalancheBridgeVerifier(bridge_);
        emit BridgeUpdated(bridge_);
    }

    function updateRelayer(address relayer_) external onlyOwner {
        if (relayer_ == address(0)) {
            revert AddressZero();
        }
        relayer = IBitcoinRelayer(relayer_);
        emit RelayerUpdated(relayer_);
    }

    function updateDex(address dex_) external onlyOwner {
        if (dex_ == address(0)) {
            revert AddressZero();
        }
        dex = IStableSwap(dex_);
        emit DexUpdated(dex_);
    }

    function updateLimits(uint256 maxBridgeAmount_, uint256 maxSlippageBps_) external onlyOwner {
        if (maxSlippageBps_ > BPS_DENOMINATOR) {
            revert SlippageBpsTooHigh();
        }
        limits = SecurityLimits({maxBridgeAmount: maxBridgeAmount_, maxSlippageBps: maxSlippageBps_});
        emit LimitsUpdated(maxBridgeAmount_, maxSlippageBps_);
    }

    function _enforceAmount(uint256 amount) internal view {
        if (limits.maxBridgeAmount != 0 && amount > limits.maxBridgeAmount) {
            revert AmountExceedsLimit(amount, limits.maxBridgeAmount);
        }
    }

    function _requiredMinOut(uint256 amount) internal view returns (uint256) {
        if (limits.maxSlippageBps == 0) {
            return 0;
        }
        uint256 basis = BPS_DENOMINATOR - limits.maxSlippageBps;
        return (amount * basis) / BPS_DENOMINATOR;
    }
}
