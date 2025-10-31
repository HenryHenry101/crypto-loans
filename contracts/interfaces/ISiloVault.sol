// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface ISiloVault {
    function deposit(uint256 amount) external returns (uint256 sharesMinted);

    function withdraw(uint256 amount) external returns (uint256 sharesBurned);

    function withdrawShares(uint256 shares) external returns (uint256 amountReturned);

    function shareToken() external view returns (address);
}
