// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IPriceOracle {
    /// @notice returns BTC/EUR price scaled by 1e18
    function btcEurPrice() external view returns (uint256);

    /// @notice returns timestamp of last update
    function lastUpdate() external view returns (uint256);
}
