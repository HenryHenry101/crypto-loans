// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {EthereumLoanCoordinator} from "../contracts/eth/EthereumLoanCoordinator.sol";
import {ICrossChainMessenger} from "../contracts/interfaces/ICrossChainMessenger.sol";
import {ChainlinkPriceOracle} from "../contracts/oracles/ChainlinkPriceOracle.sol";
import {DSTest} from "./utils/DSTest.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {MockAggregatorV3} from "./mocks/MockAggregatorV3.sol";

contract MessengerStub is ICrossChainMessenger {
    bytes public lastPayload;
    bytes public lastParams;
    address public target;

    function setTarget(address target_) external {
        target = target_;
    }

    function sendMessage(bytes calldata payload) external payable override {
        lastPayload = payload;
    }

    function deliver(bytes calldata payload, bytes calldata params) external {
        lastPayload = payload;
        lastParams = params;
        (bool ok,) = target.call(abi.encodeWithSignature("handleMessengerPayload(bytes,bytes)", payload, params));
        require(ok, "delivery failed");
    }
}

contract EthereumLoanCoordinatorTest is DSTest {
    EthereumLoanCoordinator private coordinator;
    MockERC20 private eure;
    ChainlinkPriceOracle private oracle;
    MessengerStub private messenger;
    MockAggregatorV3 private btcUsdFeed;
    MockAggregatorV3 private eurUsdFeed;
    MockAggregatorV3 private btcEurFeed;
    address private borrower = address(0xBEEF);

    function setUp() public {
        eure = new MockERC20("EURe", "EURE", 18);
        messenger = new MessengerStub();
        btcUsdFeed = new MockAggregatorV3(8);
        eurUsdFeed = new MockAggregatorV3(8);
        btcEurFeed = new MockAggregatorV3(8);
        uint256 timestamp = block.timestamp;
        btcUsdFeed.setData(int256(27_000 * 1e8), timestamp);
        eurUsdFeed.setData(int256(108_000_000), timestamp);
        btcEurFeed.setData(int256(25_000 * 1e8), timestamp);
        oracle = new ChainlinkPriceOracle(address(btcUsdFeed), address(eurUsdFeed), address(btcEurFeed));
        coordinator = new EthereumLoanCoordinator(address(eure), address(messenger), address(oracle));
        messenger.setTarget(address(coordinator));
        coordinator.setAvalancheCoordinator(address(this));
        coordinator.setAuthorizedOperator(address(this), true);
        eure.mint(address(this), 10_000 ether);
        eure.approve(address(coordinator), type(uint256).max);
    }

    function testHandleLoanCreatedViaMessenger() public {
        bytes32 loanId = keccak256("loan-1");
        bytes memory payload = abi.encode(
            "LOAN_CREATED",
            loanId,
            borrower,
            2 ether,
            1_000 ether,
            5000,
            30 days,
            block.timestamp,
            bytes("proof")
        );
        bytes memory params = abi.encode(uint64(1), bytes("avax"), bytes32("message"));
        messenger.deliver(payload, params);

        EthereumLoanCoordinator.Loan memory loan = coordinator.loans(loanId);
        assertEq(loan.principalEUR, 1_000 ether, "principal stored");
        assertEq(loan.ltvBps, 5000, "ltv stored");
        assertEq(loan.bridgeProofHash, keccak256(bytes("proof")), "proof hashed");
        uint256 expectedRepayment = (loan.principalEUR * (10000 + coordinator.COMMISSION_BPS())) / 10000;
        assertEq(loan.repaymentDue, expectedRepayment, "repayment includes commission");
    }

    function testRecordRepaymentSendsBridgeMessage() public {
        testHandleLoanCreatedViaMessenger();
        bytes32 loanId = keccak256("loan-1");
        coordinator.recordRepayment(loanId, 1_010 ether, address(this), false, bytes("bridge"));

        bytes memory expected = abi.encode("REPAYMENT_CONFIRMED", loanId, borrower, 1_010 ether, bytes("bridge"));
        assertEq(keccak256(messenger.lastPayload()), keccak256(expected), "payload matches");

        EthereumLoanCoordinator.Loan memory loan = coordinator.loans(loanId);
        assertTrue(loan.status == EthereumLoanCoordinator.LoanStatus.Repaid, "status repaid");
    }

    function testFlagDefaultSendsLiquidationOrder() public {
        testHandleLoanCreatedViaMessenger();
        bytes32 loanId = keccak256("loan-1");
        coordinator.flagDefault(loanId, bytes("swap"));
        bytes memory expected = abi.encode("LOAN_DEFAULT", loanId, borrower, 2 ether, bytes("swap"));
        assertEq(keccak256(messenger.lastPayload()), keccak256(expected), "default payload");
    }

    function testMessengerRevertsWhenPriceStale() public {
        uint256 staleTimestamp = block.timestamp - coordinator.ORACLE_TIMEOUT() - 1;
        btcEurFeed.setData(btcEurFeed.answer(), staleTimestamp);

        bytes memory payload = abi.encode(
            "LOAN_CREATED",
            bytes32("loan-2"),
            borrower,
            1 ether,
            5_000 ether,
            5000,
            30 days,
            block.timestamp,
            bytes("proof")
        );
        bytes memory params = abi.encode(uint64(1), bytes("avax"), bytes32("message-2"));

        try messenger.deliver(payload, params) {
            fail("expected oracle stale revert");
        } catch (bytes memory err) {
            bytes4 selector;
            assembly {
                selector := mload(add(err, 32))
            }
            assertEq(bytes32(selector), bytes32(EthereumLoanCoordinator.OracleStale.selector), "oracle stale selector");
        }
    }

    function testMessengerRevertsWhenPrincipalExceedsOracleLimit() public {
        bytes memory payload = abi.encode(
            "LOAN_CREATED",
            bytes32("loan-3"),
            borrower,
            1 ether,
            20_000 ether,
            5000,
            30 days,
            block.timestamp,
            bytes("proof")
        );
        bytes memory params = abi.encode(uint64(1), bytes("avax"), bytes32("message-3"));

        try messenger.deliver(payload, params) {
            fail("expected excessive principal revert");
        } catch (bytes memory err) {
            bytes4 selector;
            assembly {
                selector := mload(add(err, 32))
            }
            assertEq(bytes32(selector), bytes32(EthereumLoanCoordinator.ExcessivePrincipal.selector), "excessive principal selector");
        }
    }
}
