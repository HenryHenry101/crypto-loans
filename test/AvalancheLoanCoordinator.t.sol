// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {AvalancheLoanCoordinator} from "../contracts/ava/AvalancheLoanCoordinator.sol";
import {OwnershipToken} from "../contracts/ava/OwnershipToken.sol";
import {ICrossChainMessenger} from "../contracts/interfaces/ICrossChainMessenger.sol";
import {DSTest} from "./utils/DSTest.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {MockSiloVault} from "./mocks/MockSiloVault.sol";
import {MockPriceOracle} from "./mocks/MockPriceOracle.sol";
import {MockAvalancheBridge} from "./mocks/MockAvalancheBridge.sol";
import {MockBitcoinRelayer} from "./mocks/MockBitcoinRelayer.sol";
import {MockDexRouter} from "./mocks/MockDexRouter.sol";

contract TestMessenger is ICrossChainMessenger {
    bytes public lastPayload;
    address public lastCaller;
    address public target;

    function sendMessage(bytes calldata payload) external payable override {
        lastPayload = payload;
        lastCaller = msg.sender;
    }

    function setTarget(address target_) external {
        target = target_;
    }

    function forward(bytes calldata payload, bytes calldata params) external {
        (bool success,) = target.call(abi.encodeWithSignature("handleMessengerPayload(bytes,bytes)", payload, params));
        require(success, "forward failed");
    }
}

contract AvalancheLoanCoordinatorTest is DSTest {
    AvalancheLoanCoordinator private coordinator;
    MockERC20 private btcB;
    MockSiloVault private vault;
    MockPriceOracle private oracle;
    TestMessenger private messenger;
    MockAvalancheBridge private bridgeVerifier;
    MockBitcoinRelayer private relayer;
    MockDexRouter private dex;
    MockERC20 private stable;

    function setUp() public {
        btcB = new MockERC20("BTC.b", "BTCB", 18);
        stable = new MockERC20("EURe", "EURE", 18);
        vault = new MockSiloVault(address(btcB));
        oracle = new MockPriceOracle(20_000 ether, block.timestamp);
        messenger = new TestMessenger();
        bridgeVerifier = new MockAvalancheBridge();
        relayer = new MockBitcoinRelayer();
        dex = new MockDexRouter();
        dex.setExpectedAmountOut(1 ether);
        coordinator = new AvalancheLoanCoordinator(
            address(btcB),
            address(vault),
            address(oracle),
            address(messenger),
            address(bridgeVerifier),
            address(relayer),
            address(dex),
            address(stable),
            10 ether,
            500
        );
        messenger.setTarget(address(coordinator));
        btcB.mint(address(this), 5 ether);
        btcB.approve(address(coordinator), type(uint256).max);
        stable.mint(address(dex), 1000 ether);
    }

    function testDepositCreatesPositionAndMintsReceipt() public {
        (bytes32 loanId, uint256 principal) = coordinator.depositCollateral(1 ether, 5000, 30 days, bytes("proof"));
        AvalancheLoanCoordinator.Position memory position = coordinator.positions(loanId);
        OwnershipToken receipt = coordinator.ownershipToken();

        assertTrue(principal > 0, "principal calculated");
        assertEq(position.collateralAmount, 1 ether, "collateral stored");
        assertEq(receipt.balanceOf(address(this)), 1 ether, "receipt minted");
        assertTrue(messenger.lastPayload().length > 0, "message emitted");
        assertEq(bridgeVerifier.lastUser(), address(this), "bridge proof user");
    }

    function testRepaymentReleasesCollateral() public {
        (bytes32 loanId,) = coordinator.depositCollateral(2 ether, 6000, 30 days, bytes("proof"));
        OwnershipToken receipt = coordinator.ownershipToken();
        receipt.approve(address(coordinator), 2 ether);
        coordinator.lockOwnershipToken(loanId);

        bytes memory payload = abi.encode("REPAYMENT_CONFIRMED", loanId, address(this), uint256(0), bytes("btc-params"));
        messenger.forward(payload, bytes("unused"));

        assertEq(relayer.lastRecipient(), address(this), "recipient matches");
        assertEq(relayer.lastAmount(), 2 ether, "amount bridged");
        assertEq(relayer.lastParams(), bytes("btc-params"), "bridge params passed");
        assertEq(btcB.balanceOf(address(relayer)), 2 ether, "relayer received tokens");
    }

    function testDefaultTriggersLiquidation() public {
        (bytes32 loanId,) = coordinator.depositCollateral(1 ether, 5000, 30 days, bytes("proof"));
        dex.setExpectedAmountOut(0.99 ether);
        bytes memory swapParams = abi.encode(0.97 ether, bytes("swap"));
        bytes memory payload = abi.encode("LOAN_DEFAULT", loanId, address(this), uint256(0), swapParams);
        messenger.forward(payload, bytes("slippage"));
        assertEq(dex.lastAmountIn(), 1 ether, "dex input amount");
        assertEq(stable.balanceOf(address(this)), 0.99 ether, "stable received");
    }
}
