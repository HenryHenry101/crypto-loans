// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {AvalancheLoanCoordinator} from "../contracts/ava/AvalancheLoanCoordinator.sol";
import {OwnershipToken} from "../contracts/ava/OwnershipToken.sol";
import {ICrossChainMessenger} from "../contracts/interfaces/ICrossChainMessenger.sol";
import {ChainlinkPriceOracle} from "../contracts/oracles/ChainlinkPriceOracle.sol";
import {DSTest} from "./utils/DSTest.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {MockSiloVault} from "./mocks/MockSiloVault.sol";
import {MockAggregatorV3} from "./mocks/MockAggregatorV3.sol";
import {MockAvalancheBridge} from "./mocks/MockAvalancheBridge.sol";
import {MockBitcoinRelayer} from "./mocks/MockBitcoinRelayer.sol";
import {MockDexRouter} from "./mocks/MockDexRouter.sol";

interface Vm {
    function addr(uint256 privateKey) external returns (address);

    function prank(address msgSender) external;

    function sign(uint256 privateKey, bytes32 digest) external returns (uint8 v, bytes32 r, bytes32 s);
}

Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

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
    ChainlinkPriceOracle private oracle;
    MockAggregatorV3 private btcUsdFeed;
    MockAggregatorV3 private eurUsdFeed;
    TestMessenger private messenger;
    MockAvalancheBridge private bridgeVerifier;
    MockBitcoinRelayer private relayer;
    MockDexRouter private dex;
    MockERC20 private stable;
    address private user;

    uint256 private constant USER_PRIVATE_KEY = 0xA11CE;

    function setUp() public {
        btcB = new MockERC20("BTC.b", "BTCB", 18);
        stable = new MockERC20("EURe", "EURE", 18);
        vault = new MockSiloVault(address(btcB));
        btcUsdFeed = new MockAggregatorV3(8);
        eurUsdFeed = new MockAggregatorV3(8);
        uint256 timestamp = block.timestamp;
        btcUsdFeed.setData(int256(27_000 * 1e8), timestamp);
        eurUsdFeed.setData(int256(108_000_000), timestamp); // 1.08 * 1e8 -> 25k EUR/BTC
        oracle = new ChainlinkPriceOracle(address(btcUsdFeed), address(eurUsdFeed), address(0));
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
        user = vm.addr(USER_PRIVATE_KEY);
        btcB.mint(user, 5 ether);
        vm.prank(user);
        btcB.approve(address(coordinator), type(uint256).max);
        stable.mint(address(dex), 1000 ether);
    }

    function testDepositCreatesPositionAndMintsReceipt() public {
        uint256 expectedPrincipal = (1 ether * oracle.btcEurPrice() * 5000) / 1e18 / 10000;
        vm.prank(user);
        (bytes32 loanId, uint256 principal) = coordinator.depositCollateral(1 ether, 5000, 30 days, bytes("proof"));
        AvalancheLoanCoordinator.Position memory position = coordinator.positions(loanId);
        OwnershipToken receipt = coordinator.ownershipToken();

        assertEq(principal, expectedPrincipal, "principal calculated");
        assertEq(position.collateralAmount, 1 ether, "collateral stored");
        assertEq(receipt.balanceOf(user), 1 ether, "receipt minted");
        assertTrue(messenger.lastPayload().length > 0, "message emitted");
        assertEq(bridgeVerifier.lastUser(), user, "bridge proof user");
    }

    function testDepositRevertsWhenOracleStale() public {
        uint256 staleTimestamp = block.timestamp - coordinator.ORACLE_TIMEOUT() - 1;
        btcUsdFeed.setData(btcUsdFeed.answer(), staleTimestamp);
        eurUsdFeed.setData(eurUsdFeed.answer(), staleTimestamp);

        vm.prank(user);
        try coordinator.depositCollateral(1 ether, 5000, 30 days, bytes("proof")) {
            fail("expected oracle stale revert");
        } catch (bytes memory err) {
            bytes4 selector;
            assembly {
                selector := mload(add(err, 32))
            }
            assertEq(bytes32(selector), bytes32(AvalancheLoanCoordinator.OracleStale.selector), "oracle stale selector");
        }
    }

    function testRepaymentReleasesCollateral() public {
        vm.prank(user);
        (bytes32 loanId,) = coordinator.depositCollateral(2 ether, 6000, 30 days, bytes("proof"));
        OwnershipToken receipt = coordinator.ownershipToken();
        _permit(receipt, user, address(coordinator), 2 ether);
        vm.prank(user);
        coordinator.lockOwnershipToken(loanId);

        bytes memory payload = abi.encode("REPAYMENT_CONFIRMED", loanId, address(this), uint256(0), bytes("btc-params"));
        messenger.forward(payload, bytes("unused"));

        assertEq(relayer.lastRecipient(), address(this), "recipient matches");
        assertEq(relayer.lastAmount(), 2 ether, "amount bridged");
        assertEq(relayer.lastParams(), bytes("btc-params"), "bridge params passed");
        assertEq(btcB.balanceOf(address(relayer)), 2 ether, "relayer received tokens");
    }

    function testDirectWithdrawalByManager() public {
        vm.prank(user);
        (bytes32 loanId,) = coordinator.depositCollateral(1.5 ether, 5500, 30 days, bytes("proof"));
        OwnershipToken receipt = coordinator.ownershipToken();
        _permit(receipt, user, address(coordinator), 1.5 ether);
        vm.prank(user);
        coordinator.lockOwnershipToken(loanId);

        coordinator.setEthereumLoanManager(address(this));

        coordinator.initiateWithdrawal(loanId, address(0xBEEF), bytes("manual"));

        assertEq(relayer.lastRecipient(), address(0xBEEF), "manual recipient");
        assertEq(relayer.lastAmount(), 1.5 ether, "manual amount");
        assertEq(relayer.lastParams(), bytes("manual"), "manual params");
        AvalancheLoanCoordinator.Position memory position = coordinator.positions(loanId);
        assertEq(uint256(position.state), uint256(AvalancheLoanCoordinator.LoanState.Released), "state released");
    }

    function testKeeperLiquidationFlow() public {
        vm.prank(user);
        (bytes32 loanId,) = coordinator.depositCollateral(1 ether, 5000, 30 days, bytes("proof"));
        coordinator.setKeeper(address(this), true);
        dex.setExpectedAmountOut(0.98 ether);

        coordinator.liquidate(loanId, address(this), abi.encode(0.95 ether, bytes("swap")));

        assertEq(dex.lastAmountIn(), 1 ether, "keeper liquidation amount");
        assertEq(stable.balanceOf(address(this)), 0.98 ether, "keeper proceeds");
        AvalancheLoanCoordinator.Position memory position = coordinator.positions(loanId);
        assertEq(uint256(position.state), uint256(AvalancheLoanCoordinator.LoanState.Defaulted), "state defaulted");
    }

    function testUnauthorizedDirectCallsRevert() public {
        vm.prank(user);
        (bytes32 loanId,) = coordinator.depositCollateral(1 ether, 5000, 30 days, bytes("proof"));
        OwnershipToken receipt = coordinator.ownershipToken();
        _permit(receipt, user, address(coordinator), 1 ether);
        vm.prank(user);
        coordinator.lockOwnershipToken(loanId);

        try coordinator.initiateWithdrawal(loanId, address(this), bytes("manual")) {
            fail("expected authorization revert");
        } catch (bytes memory err) {
            bytes4 selector;
            assembly {
                selector := mload(add(err, 32))
            }
            assertEq(bytes32(selector), bytes32(AvalancheLoanCoordinator.NotAuthorized.selector), "unauthorized withdrawal");
        }

        try coordinator.liquidate(loanId, address(this), abi.encode(0.9 ether, bytes("swap"))) {
            fail("expected authorization revert");
        } catch (bytes memory err2) {
            bytes4 selector2;
            assembly {
                selector2 := mload(add(err2, 32))
            }
            assertEq(bytes32(selector2), bytes32(AvalancheLoanCoordinator.NotAuthorized.selector), "unauthorized liquidation");
        }
    }

    function testDefaultTriggersLiquidation() public {
        vm.prank(user);
        (bytes32 loanId,) = coordinator.depositCollateral(1 ether, 5000, 30 days, bytes("proof"));
        dex.setExpectedAmountOut(0.99 ether);
        bytes memory swapParams = abi.encode(0.97 ether, bytes("swap"));
        bytes memory payload = abi.encode("LOAN_DEFAULT", loanId, address(this), uint256(0), swapParams);
        messenger.forward(payload, bytes("slippage"));
        assertEq(dex.lastAmountIn(), 1 ether, "dex input amount");
        assertEq(stable.balanceOf(address(this)), 0.99 ether, "stable received");
    }

    function testRestrictsUnauthorizedTransfers() public {
        vm.prank(user);
        coordinator.depositCollateral(1 ether, 5000, 30 days, bytes("proof"));
        OwnershipToken receipt = coordinator.ownershipToken();

        vm.prank(user);
        try receipt.transfer(address(0xBEEF), 0.5 ether) {
            fail("expected transfer restriction");
        } catch (bytes memory err) {
            bytes4 selector;
            assembly {
                selector := mload(add(err, 32))
            }
            assertEq(bytes32(selector), bytes32(OwnershipToken.UnauthorizedTransfer.selector), "transfer blocked");
        }
    }

    function _permit(OwnershipToken receipt, address owner, address spender, uint256 value) private {
        uint256 nonce = receipt.nonces(owner);
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 structHash = keccak256(
            abi.encode(receipt.PERMIT_TYPEHASH(), owner, spender, value, nonce, deadline)
        );
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", receipt.DOMAIN_SEPARATOR(), structHash));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(USER_PRIVATE_KEY, digest);
        receipt.permit(owner, spender, value, deadline, v, r, s);
        assertEq(receipt.allowance(owner, spender), value, "permit allowance");
    }
}
