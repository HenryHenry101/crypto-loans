// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {AvalancheLoanCoordinator} from "../contracts/ava/AvalancheLoanCoordinator.sol";
import {OwnershipToken} from "../contracts/ava/OwnershipToken.sol";
import {ICrossChainMessenger} from "../contracts/interfaces/ICrossChainMessenger.sol";
import {DSTest} from "./utils/DSTest.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {MockSiloVault} from "./mocks/MockSiloVault.sol";
import {MockPriceOracle} from "./mocks/MockPriceOracle.sol";
import {MockBridgeAdapter} from "./mocks/MockBridgeAdapter.sol";

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
    MockBridgeAdapter private bridge;

    function setUp() public {
        btcB = new MockERC20("BTC.b", "BTCB", 18);
        vault = new MockSiloVault(address(btcB));
        oracle = new MockPriceOracle(20_000 ether, block.timestamp);
        messenger = new TestMessenger();
        bridge = new MockBridgeAdapter();
        coordinator = new AvalancheLoanCoordinator(
            address(btcB),
            address(vault),
            address(oracle),
            address(messenger),
            address(bridge)
        );
        messenger.setTarget(address(coordinator));
        btcB.mint(address(this), 5 ether);
        btcB.approve(address(coordinator), type(uint256).max);
    }

    function testDepositCreatesPositionAndMintsReceipt() public {
        (bytes32 loanId, uint256 principal) = coordinator.depositCollateral(1 ether, 5000, 30 days, hex"");
        AvalancheLoanCoordinator.Position memory position = coordinator.positions(loanId);
        OwnershipToken receipt = coordinator.ownershipToken();

        assertTrue(principal > 0, "principal calculated");
        assertEq(position.collateralAmount, 1 ether, "collateral stored");
        assertEq(receipt.balanceOf(address(this)), 1 ether, "receipt minted");
        assertTrue(messenger.lastPayload().length > 0, "message emitted");
    }

    function testRepaymentReleasesCollateral() public {
        (bytes32 loanId,) = coordinator.depositCollateral(2 ether, 6000, 30 days, hex"");
        OwnershipToken receipt = coordinator.ownershipToken();
        receipt.approve(address(coordinator), 2 ether);
        coordinator.lockOwnershipToken(loanId);

        bytes memory payload = abi.encode("REPAYMENT_CONFIRMED", loanId, address(this), uint256(0), bytes("proof"));
        messenger.forward(payload, bytes("btc-params"));

        assertEq(bridge.lastRecipient(), address(this), "recipient matches");
        assertEq(bridge.lastAmount(), 2 ether, "amount bridged");
    }

    function testDefaultTriggersLiquidation() public {
        (bytes32 loanId,) = coordinator.depositCollateral(1 ether, 5000, 30 days, hex"");
        bytes memory payload = abi.encode("LOAN_DEFAULT", loanId, address(this), uint256(0), bytes("swap"));
        messenger.forward(payload, bytes("slippage"));

        assertTrue(bridge.unwindCalled(), "liquidation path");
    }
}
