// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {DSTest} from "./utils/DSTest.sol";
import {AvalancheBridgeAdapter} from "../contracts/bridge/AvalancheBridgeAdapter.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {MockAvalancheBridge} from "./mocks/MockAvalancheBridge.sol";
import {MockBitcoinRelayer} from "./mocks/MockBitcoinRelayer.sol";
import {MockDexRouter} from "./mocks/MockDexRouter.sol";

contract AvalancheBridgeAdapterTest is DSTest {
    AvalancheBridgeAdapter private adapter;
    MockERC20 private btcB;
    MockERC20 private stable;
    MockAvalancheBridge private bridge;
    MockBitcoinRelayer private relayer;
    MockDexRouter private dex;

    function setUp() public {
        btcB = new MockERC20("BTC.b", "BTCB", 18);
        stable = new MockERC20("EURe", "EURE", 18);
        bridge = new MockAvalancheBridge();
        relayer = new MockBitcoinRelayer();
        dex = new MockDexRouter();
        dex.setExpectedAmountOut(0.99 ether);

        adapter = new AvalancheBridgeAdapter(
            address(btcB),
            address(stable),
            address(bridge),
            address(relayer),
            address(dex),
            10 ether,
            500,
            address(this)
        );

        stable.mint(address(dex), 10 ether);
    }

    function testValidateBridgeProofCallsVerifier() public {
        bool valid = adapter.validateBridgeProof(address(this), 1 ether, bytes("proof"));
        assertTrue(valid, "proof should be valid");
        assertEq(bridge.lastUser(), address(this), "user recorded");
        assertEq(bridge.lastAmount(), 1 ether, "amount recorded");
    }

    function testValidateBridgeProofRespectsLimit() public {
        (bool success,) = address(adapter).call(
            abi.encodeWithSignature("validateBridgeProof(address,uint256,bytes)", address(this), 20 ether, bytes("proof"))
        );
        assertTrue(!success, "amount above limit should revert");
    }

    function testBridgeToBitcoinSendsTokensToRelayer() public {
        btcB.mint(address(this), 2 ether);
        btcB.approve(address(adapter), type(uint256).max);

        adapter.bridgeToBitcoin(address(0xBEEF), 2 ether, bytes("params"));

        assertEq(btcB.balanceOf(address(relayer)), 2 ether, "relayer balance");
        assertEq(relayer.lastRecipient(), address(0xBEEF), "recipient forwarded");
        assertEq(relayer.lastAmount(), 2 ether, "amount forwarded");
    }

    function testUnwindToStableSwapsViaDex() public {
        btcB.mint(address(this), 1 ether);
        btcB.approve(address(adapter), type(uint256).max);

        bytes memory params = abi.encode(0.95 ether, bytes("swap-data"));
        adapter.unwindToStable(address(0xCAFE), 1 ether, params);

        assertEq(dex.lastTokenIn(), address(btcB), "token in");
        assertEq(dex.lastTokenOut(), address(stable), "token out");
        assertEq(stable.balanceOf(address(0xCAFE)), 0.99 ether, "stable received");
    }

    function testUnwindToStableRevertsWhenMinOutTooLow() public {
        btcB.mint(address(this), 1 ether);
        btcB.approve(address(adapter), type(uint256).max);
        bytes memory params = abi.encode(0.10 ether, bytes("swap"));
        (bool success,) = address(adapter).call(
            abi.encodeWithSignature(
                "unwindToStable(address,uint256,bytes)", address(this), 1 ether, params
            )
        );
        assertTrue(!success, "min amount below guard should fail");
    }
}
