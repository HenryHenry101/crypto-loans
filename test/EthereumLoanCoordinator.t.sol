// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {EthereumLoanCoordinator} from "../contracts/eth/EthereumLoanCoordinator.sol";
import {ICrossChainMessenger} from "../contracts/interfaces/ICrossChainMessenger.sol";
import {DSTest} from "./utils/DSTest.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {MockPriceOracle} from "./mocks/MockPriceOracle.sol";

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
    MockPriceOracle private oracle;
    MessengerStub private messenger;
    address private borrower = address(0xBEEF);

    function setUp() public {
        eure = new MockERC20("EURe", "EURE", 18);
        oracle = new MockPriceOracle(30_000 ether, block.timestamp);
        messenger = new MessengerStub();
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
}
