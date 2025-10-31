// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract MockPriceOracle {
    uint256 public price;
    uint256 public lastTimestamp;

    constructor(uint256 price_, uint256 lastUpdate_) {
        price = price_;
        lastTimestamp = lastUpdate_;
    }

    function setPrice(uint256 newPrice) external {
        price = newPrice;
        lastTimestamp = block.timestamp;
    }

    function btcEurPrice() external view returns (uint256) {
        return price;
    }

    function lastUpdate() external view returns (uint256) {
        return lastTimestamp;
    }
}
