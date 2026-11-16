// SPDX-License-Identifier: MIT
pragma solidity ^0.8.29;

import { IPayable } from "@reactive/src/interfaces/IPayable.sol";
import { AbstractCallback } from "@reactive/src/base/AbstractCallback.sol";
import { IERC20 } from "./IERC20.sol";

/// @title SafeBucket — segregated holding contract for protected funds.
/// @notice While protection is active, vault funds physically sit here, in a
///         separate contract that can only release them back to the vault.
contract SafeBucket {
    IERC20 public immutable token;
    address public immutable vault;

    error OnlyVault();

    constructor(address token_) {
        token = IERC20(token_);
        vault = msg.sender;
    }

    /// @notice Send `amount` of the token back to the vault.
    function releaseToVault(uint256 amount) external {
        if (msg.sender != vault) revert OnlyVault();
        require(token.transfer(vault, amount), "SafeBucket: transfer");
    }

    function balance() external view returns (uint256) {
        return token.balanceOf(address(this));
    }
}

/// @title GuardianVault — user vault on Base Sepolia that obeys the guardian.
/// @notice Users deposit MockUSD. In calm times funds sit in the vault ("risky"
///         allocation, e.g. earning yield). When the SentimentGuardian on Lasna
///         reacts to a risk-off AI signal, its callback lands here and every
///         token is moved into the SafeBucket until the all-clear callback.
///         Callbacks are authenticated twice: the caller must be the Reactive
///         callback proxy, and the injected sender must be our guardian.
contract GuardianVault is AbstractCallback {
    IERC20 public immutable token;
    SafeBucket public immutable safeBucket;

    mapping(address => uint256) public deposits;
    uint256 public totalDeposits;

    bool public protectionActive;
    int256 public lastAlertScore;
    uint256 public protectionsTriggered;
    uint256 public lastProtectedAt;
    uint256 public lastClearedAt;

    event Deposited(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);
    event Protected(int256 score, uint256 amountMoved);
    event ProtectionCleared(int256 score, uint256 amountMoved);

    error InsufficientDeposit();

    /// @param callbackProxy_ Reactive callback proxy on Base Sepolia.
    /// @param guardian_      SentimentGuardian address on Lasna (callback sender).
    /// @param token_         ERC-20 the vault holds (MockUSD on testnet).
    constructor(IPayable callbackProxy_, address guardian_, address token_)
        payable
        AbstractCallback(callbackProxy_, guardian_)
    {
        token = IERC20(token_);
        safeBucket = new SafeBucket(token_);
    }

    /// @notice Deposit tokens. During protection they are forwarded straight
    ///         to the safe bucket, so new money is protected too.
    function deposit(uint256 amount) external {
        require(token.transferFrom(msg.sender, address(this), amount), "Vault: transferFrom");
        deposits[msg.sender] += amount;
        totalDeposits += amount;
        if (protectionActive) {
            require(token.transfer(address(safeBucket), amount), "Vault: forward");
        }
        emit Deposited(msg.sender, amount);
    }

    /// @notice Withdraw your deposit. Works in both modes: during protection
    ///         the vault first pulls your share back from the safe bucket.
    function withdraw(uint256 amount) external {
        if (deposits[msg.sender] < amount) revert InsufficientDeposit();
        deposits[msg.sender] -= amount;
        totalDeposits -= amount;
        if (protectionActive) {
            safeBucket.releaseToVault(amount);
        }
        require(token.transfer(msg.sender, amount), "Vault: transfer");
        emit Withdrawn(msg.sender, amount);
    }

    /// @notice Callback from the guardian: risk-off. Move everything to safety.
    function onRiskAlert(address reactive_, int256 score_)
        external
        onlyServiceProvider
        onlyCallbackSender(reactive_)
    {
        if (!protectionActive) {
            protectionActive = true;
            protectionsTriggered += 1;
            uint256 bal = token.balanceOf(address(this));
            emit Protected(score_, bal);
            if (bal > 0) {
                require(token.transfer(address(safeBucket), bal), "Vault: protect transfer");
            }
        }
        lastAlertScore = score_;
        lastProtectedAt = block.timestamp;
    }

    /// @notice Callback from the guardian: risk cleared. Move everything back.
    function onRiskCleared(address reactive_, int256 score_)
        external
        onlyServiceProvider
        onlyCallbackSender(reactive_)
    {
        if (protectionActive) {
            protectionActive = false;
            uint256 bal = token.balanceOf(address(safeBucket));
            emit ProtectionCleared(score_, bal);
            if (bal > 0) {
                safeBucket.releaseToVault(bal);
            }
        }
        lastClearedAt = block.timestamp;
    }

    /// @notice Tokens currently in the "risky" allocation (this contract).
    function riskyBalance() external view returns (uint256) {
        return token.balanceOf(address(this));
    }

    /// @notice Tokens currently in the "safe" allocation (the SafeBucket).
    function safeBalance() external view returns (uint256) {
        return token.balanceOf(address(safeBucket));
    }

    /// @notice Settles outstanding callback debt from this contract's balance.
    function coverDebt() external {
        _coverDebt();
    }
}
