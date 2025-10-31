// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IERC20} from "../../contracts/libs/SafeERC20.sol";

contract MockDexRouter {
    uint256 public expectedAmountOut;
    address public lastTokenIn;
    address public lastTokenOut;
    uint256 public lastAmountIn;
    bytes public lastData;

    function setExpectedAmountOut(uint256 amount) external {
        expectedAmountOut = amount;
    }

    function swapExactInput(address tokenIn, address tokenOut, uint256 amountIn, bytes calldata data)
        external
        returns (uint256 amountOut)
    {
        lastTokenIn = tokenIn;
        lastTokenOut = tokenOut;
        lastAmountIn = amountIn;
        lastData = data;

        IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn);
        IERC20(tokenOut).transfer(msg.sender, expectedAmountOut);

        return expectedAmountOut;
    }
}
