// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "../libs/Ownable.sol";

/// @title OwnershipToken
/// @notice ERC20-like token representing claim over collateral BTC.b deposits.
contract OwnershipToken is Ownable {
    string public name;
    string public symbol;
    uint8 public immutable decimals;

    mapping(address => uint256) private _balances;
    mapping(address => mapping(address => uint256)) private _allowances;
    mapping(address => uint256) private _nonces;
    uint256 private _totalSupply;

    bytes32 private immutable _DOMAIN_SEPARATOR;
    uint256 private immutable _DOMAIN_CHAIN_ID;
    bytes32 private immutable _HASHED_NAME;

    bytes32 private constant _EIP712_DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 private constant _HASHED_VERSION = keccak256(bytes("1"));

    /// @notice Typehash used to build EIP-2612 permits.
    bytes32 public constant PERMIT_TYPEHASH =
        keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)");

    event Transfer(address indexed from, address indexed to, uint256 amount);
    event Approval(address indexed owner, address indexed spender, uint256 amount);

    error InsufficientBalance();
    error InsufficientAllowance();
    error PermitExpired();
    error InvalidSignature();
    error UnauthorizedTransfer();

    constructor(string memory name_, string memory symbol_, uint8 decimals_) {
        name = name_;
        symbol = symbol_;
        decimals = decimals_;
        _HASHED_NAME = keccak256(bytes(name_));
        _DOMAIN_CHAIN_ID = block.chainid;
        _DOMAIN_SEPARATOR = _buildDomainSeparator(block.chainid);
    }

    function totalSupply() external view returns (uint256) {
        return _totalSupply;
    }

    function balanceOf(address account) external view returns (uint256) {
        return _balances[account];
    }

    function allowance(address owner_, address spender) external view returns (uint256) {
        return _allowances[owner_][spender];
    }

    function nonces(address owner_) external view returns (uint256) {
        return _nonces[owner_];
    }

    function DOMAIN_SEPARATOR() public view returns (bytes32) {
        if (block.chainid == _DOMAIN_CHAIN_ID) {
            return _DOMAIN_SEPARATOR;
        }
        return _buildDomainSeparator(block.chainid);
    }

    /// @notice Approves `spender` to spend `value` tokens on behalf of `owner_` using an EIP-2612 signature.
    /// @dev Stores and increments the nonce for `owner_` following EIP-712 rules.
    /// @param owner_ The token holder granting the approval.
    /// @param spender The address allowed to spend the tokens.
    /// @param value The amount of tokens approved for spending.
    /// @param deadline Timestamp after which the permit is no longer valid.
    /// @param v Signature recovery byte.
    /// @param r First 32 bytes of the ECDSA signature.
    /// @param s Second 32 bytes of the ECDSA signature.
    function permit(
        address owner_,
        address spender,
        uint256 value,
        uint256 deadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external {
        if (block.timestamp > deadline) {
            revert PermitExpired();
        }

        uint256 nonce = _useNonce(owner_);
        bytes32 structHash = keccak256(abi.encode(PERMIT_TYPEHASH, owner_, spender, value, nonce, deadline));
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR(), structHash));

        address signer = ecrecover(digest, v, r, s);
        if (signer == address(0) || signer != owner_) {
            revert InvalidSignature();
        }

        _approve(owner_, spender, value);
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        _approve(msg.sender, spender, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 currentAllowance = _allowances[from][msg.sender];
        if (currentAllowance < amount) {
            revert InsufficientAllowance();
        }
        _approve(from, msg.sender, currentAllowance - amount);
        _transfer(from, to, amount);
        return true;
    }

    function mint(address to, uint256 amount) external onlyOwner {
        _totalSupply += amount;
        _balances[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    function burn(address from, uint256 amount) external onlyOwner {
        uint256 currentBalance = _balances[from];
        if (currentBalance < amount) {
            revert InsufficientBalance();
        }
        _balances[from] = currentBalance - amount;
        _totalSupply -= amount;
        emit Transfer(from, address(0), amount);
    }

    function _transfer(address from, address to, uint256 amount) internal {
        if (from != owner() && to != owner()) {
            revert UnauthorizedTransfer();
        }
        if (_balances[from] < amount) {
            revert InsufficientBalance();
        }
        _balances[from] -= amount;
        _balances[to] += amount;
        emit Transfer(from, to, amount);
    }

    function _approve(address owner_, address spender, uint256 amount) internal {
        _allowances[owner_][spender] = amount;
        emit Approval(owner_, spender, amount);
    }

    function _buildDomainSeparator(uint256 chainId) private view returns (bytes32) {
        return keccak256(
            abi.encode(_EIP712_DOMAIN_TYPEHASH, _HASHED_NAME, _HASHED_VERSION, chainId, address(this))
        );
    }

    function _useNonce(address owner_) private returns (uint256 current) {
        current = _nonces[owner_];
        _nonces[owner_] = current + 1;
    }
}
