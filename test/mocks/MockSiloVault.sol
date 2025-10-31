// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {MockERC20} from "./MockERC20.sol";

contract MockSiloVault {
    MockERC20 public immutable asset;
    MockERC20 public immutable share;

    mapping(address => uint256) public sharesOf;

    constructor(address asset_) {
        asset = MockERC20(asset_);
        share = new MockERC20("Silo Shares", "sSHARE", 18);
    }

    function deposit(uint256 amount) external returns (uint256 sharesMinted) {
        require(asset.transferFrom(msg.sender, address(this), amount));
        sharesOf[msg.sender] += amount;
        sharesMinted = amount;
        share.mint(msg.sender, amount);
    }

    function withdraw(uint256 amount) external returns (uint256 sharesBurned) {
        return withdrawShares(amount);
    }

    function withdrawShares(uint256 sharesAmount) public returns (uint256 amountReturned) {
        uint256 current = sharesOf[msg.sender];
        require(current >= sharesAmount, "shares");
        sharesOf[msg.sender] = current - sharesAmount;
        require(asset.transfer(msg.sender, sharesAmount));
        amountReturned = sharesAmount;
    }

    function shareToken() external view returns (address) {
        return address(share);
    }
}
