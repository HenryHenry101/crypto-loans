// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IPriceOracle} from "../interfaces/IPriceOracle.sol";
import {AggregatorV3Interface} from "./AggregatorV3Interface.sol";

/// @title ChainlinkPriceOracle
/// @notice Aggregates Chainlink BTC/USD and EUR/USD feeds (or an optional BTC/EUR feed)
///         to produce a BTC/EUR price scaled to 1e18.
contract ChainlinkPriceOracle is IPriceOracle {
    error InvalidFeedConfig();
    error InvalidOracleAnswer();

    AggregatorV3Interface public immutable btcUsdFeed;
    AggregatorV3Interface public immutable eurUsdFeed;
    AggregatorV3Interface public immutable btcEurFeed;

    uint8 public immutable btcUsdDecimals;
    uint8 public immutable eurUsdDecimals;
    uint8 public immutable btcEurDecimals;

    constructor(address btcUsdFeed_, address eurUsdFeed_, address btcEurFeed_) {
        if (btcEurFeed_ == address(0) && (btcUsdFeed_ == address(0) || eurUsdFeed_ == address(0))) {
            revert InvalidFeedConfig();
        }

        if (btcUsdFeed_ != address(0)) {
            btcUsdFeed = AggregatorV3Interface(btcUsdFeed_);
            btcUsdDecimals = AggregatorV3Interface(btcUsdFeed_).decimals();
        }
        if (eurUsdFeed_ != address(0)) {
            eurUsdFeed = AggregatorV3Interface(eurUsdFeed_);
            eurUsdDecimals = AggregatorV3Interface(eurUsdFeed_).decimals();
        }
        if (btcEurFeed_ != address(0)) {
            btcEurFeed = AggregatorV3Interface(btcEurFeed_);
            btcEurDecimals = AggregatorV3Interface(btcEurFeed_).decimals();
        }
    }

    /// @inheritdoc IPriceOracle
    function btcEurPrice() external view override returns (uint256) {
        if (address(btcEurFeed) != address(0)) {
            (int256 answer,) = _latestRound(btcEurFeed);
            uint256 price = _scaleTo1e18(uint256(answer), btcEurDecimals);
            if (price == 0) revert InvalidOracleAnswer();
            return price;
        }

        (int256 btcUsdRaw,) = _latestRound(btcUsdFeed);
        (int256 eurUsdRaw,) = _latestRound(eurUsdFeed);

        uint256 btcUsd = _scaleTo1e18(uint256(btcUsdRaw), btcUsdDecimals);
        uint256 eurUsd = _scaleTo1e18(uint256(eurUsdRaw), eurUsdDecimals);
        if (btcUsd == 0) revert InvalidOracleAnswer();
        if (eurUsd == 0) revert InvalidOracleAnswer();
        return (btcUsd * 1e18) / eurUsd;
    }

    /// @inheritdoc IPriceOracle
    function lastUpdate() external view override returns (uint256) {
        if (address(btcEurFeed) != address(0)) {
            (, uint256 updatedAt) = _latestRound(btcEurFeed);
            return updatedAt;
        }

        (, uint256 btcUsdUpdatedAt) = _latestRound(btcUsdFeed);
        (, uint256 eurUsdUpdatedAt) = _latestRound(eurUsdFeed);
        return btcUsdUpdatedAt < eurUsdUpdatedAt ? btcUsdUpdatedAt : eurUsdUpdatedAt;
    }

    function _latestRound(AggregatorV3Interface feed) internal view returns (int256 answer, uint256 updatedAt) {
        if (address(feed) == address(0)) revert InvalidFeedConfig();
        (, answer,, updatedAt,) = feed.latestRoundData();
        if (answer <= 0 || updatedAt == 0) revert InvalidOracleAnswer();
    }

    function _scaleTo1e18(uint256 value, uint8 decimals_) internal pure returns (uint256) {
        if (decimals_ == 18) return value;
        if (decimals_ < 18) {
            return value * (10 ** (18 - decimals_));
        }
        return value / (10 ** (decimals_ - 18));
    }
}
