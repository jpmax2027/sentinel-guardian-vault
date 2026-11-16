// SPDX-License-Identifier: MIT
pragma solidity ^0.8.29;

import { ISystemContract } from "@reactive/src/interfaces/ISystemContract.sol";
import { IReactive } from "@reactive/src/interfaces/IReactive.sol";
import { AbstractReactive } from "@reactive/src/base/AbstractReactive.sol";

/// @title SentimentGuardian — reactive brain of the Sentinel vault (Reactive Lasna).
/// @notice Subscribes to `SignalPosted` events from the SignalOracle on Base Sepolia.
///         When the AI score crosses the risk-off threshold it orders the GuardianVault
///         (via a Reactive callback) to move user funds into the safe bucket; when the
///         score recovers past the risk-on threshold it orders them back. Nobody polls,
///         nobody runs a keeper: the contract reacts on its own, in about a second.
contract SentimentGuardian is AbstractReactive {
    /// @notice topic0 of SignalOracle.SignalPosted(int256,uint256,uint256,uint256).
    uint256 public constant SIGNAL_TOPIC0 =
        uint256(keccak256("SignalPosted(int256,uint256,uint256,uint256)"));

    uint64 private constant CALLBACK_GAS_LIMIT = 1_000_000;

    uint256 public immutable originChainId;
    address public immutable oracle;
    uint256 public immutable destChainId;

    address public owner;
    address public vault;

    int256 public riskOffThreshold;
    int256 public riskOnThreshold;
    bool public protectionActive;

    // Observability: everything a judge needs to see the loop working.
    uint256 public signalsSeen;
    uint256 public callbacksSent;
    int256 public lastScore;
    uint256 public lastConfidence;
    uint256 public lastSignalPostedAt;
    uint256 public lastOriginBlock;
    uint256 public lastReactBlock;

    event VaultSet(address indexed vault);
    event ThresholdsSet(int256 riskOff, int256 riskOn);
    event SignalHandled(int256 score, uint256 confidence, bool protectionActive);
    event CallbackRequested(int256 score, bool protect);

    error NotOwner();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    /// @param originChainId_ Chain the SignalOracle lives on (Base Sepolia = 84532).
    /// @param oracle_        SignalOracle address.
    /// @param destChainId_   Chain the GuardianVault lives on (Base Sepolia = 84532).
    /// @param riskOff_       Score at/below which protection engages (e.g. -30).
    /// @param riskOn_        Score at/above which protection releases (e.g. 20).
    constructor(
        uint256 originChainId_,
        address oracle_,
        uint256 destChainId_,
        int256 riskOff_,
        int256 riskOn_
    ) payable {
        originChainId = originChainId_;
        oracle = oracle_;
        destChainId = destChainId_;
        riskOffThreshold = riskOff_;
        riskOnThreshold = riskOn_;
        owner = msg.sender;

        SYSTEM.subscribe(
            originChainId_,
            oracle_,
            SIGNAL_TOPIC0,
            REACTIVE_IGNORE,
            REACTIVE_IGNORE,
            REACTIVE_IGNORE
        );
    }

    /// @notice Wire the destination vault after it is deployed (it needs this
    ///         contract's address at construction, so the cycle breaks here).
    function setVault(address vault_) external onlyOwner {
        vault = vault_;
        emit VaultSet(vault_);
    }

    function setThresholds(int256 riskOff_, int256 riskOn_) external onlyOwner {
        riskOffThreshold = riskOff_;
        riskOnThreshold = riskOn_;
        emit ThresholdsSet(riskOff_, riskOn_);
    }

    /// @notice Settles outstanding debt to the system contract from this
    ///         contract's own balance. Open to anyone: funding the guardian
    ///         back to life is a public good.
    function coverDebt() external {
        _coverDebt();
    }

    /// @inheritdoc IReactive
    function react(LogRecord memory log_) external onlySystem {
        // Not our event / not our oracle: fall through quietly (never revert —
        // a revert still bills the contract and helps nobody).
        if (log_.topic0 != SIGNAL_TOPIC0 || log_.contractAddress != oracle) {
            return;
        }

        (int256 score, uint256 confidence, uint256 postedAt,) =
            abi.decode(log_.data, (int256, uint256, uint256, uint256));

        signalsSeen += 1;
        lastScore = score;
        lastConfidence = confidence;
        lastSignalPostedAt = postedAt;
        lastOriginBlock = log_.blockNumber;
        lastReactBlock = block.number;

        if (vault != address(0)) {
            if (!protectionActive && score <= riskOffThreshold) {
                protectionActive = true;
                _requestVaultCallback(true, score);
            } else if (protectionActive && score >= riskOnThreshold) {
                protectionActive = false;
                _requestVaultCallback(false, score);
            }
        }

        emit SignalHandled(score, confidence, protectionActive);
    }

    function _requestVaultCallback(bool protect_, int256 score_) internal {
        // The first argument is reserved: Reactive overwrites it with this
        // contract's address so the vault can authenticate the callback.
        bytes memory payload = protect_
            ? abi.encodeWithSignature("onRiskAlert(address,int256)", address(0), score_)
            : abi.encodeWithSignature("onRiskCleared(address,int256)", address(0), score_);

        SYSTEM.requestCallbackV_1_0(
            ISystemContract.CallbackConfiguration_V_1_0({
                chainId: destChainId,
                recipient: vault,
                gasLimit: CALLBACK_GAS_LIMIT,
                payload: payload
            })
        );

        callbacksSent += 1;
        emit CallbackRequested(score_, protect_);
    }
}
