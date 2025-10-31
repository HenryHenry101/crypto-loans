// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20 {
    function totalSupply() external view returns (uint256);

    function balanceOf(address account) external view returns (uint256);

    function allowance(address owner, address spender) external view returns (uint256);

    function transfer(address to, uint256 amount) external returns (bool);

    function approve(address spender, uint256 amount) external returns (bool);

    function transferFrom(address from, address to, uint256 amount) external returns (bool);

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
}

library SafeERC20 {
    function safeTransfer(IERC20 token, address to, uint256 value) internal {
        bool success = token.transfer(to, value);
        require(success, "SafeERC20: transfer failed");
    }

    function safeTransferFrom(IERC20 token, address from, address to, uint256 value) internal {
        bool success = token.transferFrom(from, to, value);
        require(success, "SafeERC20: transferFrom failed");
    }

    function safeApprove(IERC20 token, address spender, uint256 value) internal {
        bool success = token.approve(spender, value);
        require(success, "SafeERC20: approve failed");
    }
}
