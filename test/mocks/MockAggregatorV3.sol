// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {AggregatorV3Interface} from "../../contracts/oracles/AggregatorV3Interface.sol";

contract MockAggregatorV3 is AggregatorV3Interface {
    uint8 public override decimals;
    int256 public answer;
    uint256 public latestTimestamp;
    uint80 private _roundId;

    constructor(uint8 decimals_) {
        decimals = decimals_;
        _roundId = 1;
    }

    function setData(int256 answer_, uint256 timestamp) external {
        answer = answer_;
        latestTimestamp = timestamp;
        _roundId += 1;
    }

    function latestRoundData()
        external
        view
        override
        returns (uint80 roundId, int256 answer_, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound)
    {
        roundId = _roundId;
        answer_ = answer;
        startedAt = latestTimestamp;
        updatedAt = latestTimestamp;
        answeredInRound = _roundId;
    }
}
