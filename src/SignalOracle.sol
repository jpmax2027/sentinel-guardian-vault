// SPDX-License-Identifier: MIT
pragma solidity ^0.8.29;

/// @title SignalOracle — on-chain inbox for AI market-risk signals (Base Sepolia).
/// @notice An off-chain AI agent (see `agent/signal_agent.py`) scores market risk
///         from live price data and posts its score here. Posting emits
///         `SignalPosted`, the event the reactive contract on Lasna subscribes to.
///         The AI is part of the running system: no signal, no reaction.
contract SignalOracle {
    /// @notice Emitted on every posted signal. This is the subscribed event.
    /// @param score      Risk score in [-100, 100]: negative = risk-off, positive = risk-on.
    /// @param confidence Model confidence in [0, 100].
    /// @param postedAt   Block timestamp of the post.
    /// @param seq        Monotonic signal sequence number.
    event SignalPosted(int256 score, uint256 confidence, uint256 postedAt, uint256 seq);

    address public owner;
    address public agent;

    int256 public latestScore;
    uint256 public latestConfidence;
    uint256 public latestAt;
    uint256 public seq;

    error NotOwner();
    error NotAgent();
    error ScoreOutOfRange();
    error ConfidenceOutOfRange();

    constructor(address agent_) {
        owner = msg.sender;
        agent = agent_;
    }

    function setAgent(address agent_) external {
        if (msg.sender != owner) revert NotOwner();
        agent = agent_;
    }

    /// @notice Post a new AI risk signal. Only the authorised AI agent may call.
    function postSignal(int256 score_, uint256 confidence_) external {
        if (msg.sender != agent) revert NotAgent();
        if (score_ < -100 || score_ > 100) revert ScoreOutOfRange();
        if (confidence_ > 100) revert ConfidenceOutOfRange();

        seq += 1;
        latestScore = score_;
        latestConfidence = confidence_;
        latestAt = block.timestamp;

        emit SignalPosted(score_, confidence_, block.timestamp, seq);
    }
}
