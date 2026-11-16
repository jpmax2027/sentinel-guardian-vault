# DoraHacks submission draft — Reactive Omni Buildathon

**Project name:** Sentinel — AI-Signal Guardian Vault

**Track:** Reactive Meets AI (primary) · also eligible: Set It and Forget It

**Tagline:** An AI risk score, a reactive contract, and a vault that moves your
money to safety by itself — across two chains, in about a second, with no
keeper and no bot server.

**Description:**
Sentinel is an autonomous protection layer for stablecoin holders. A small,
transparent AI scoring model (features: 24h return, EMA trend, RSI, realised
volatility; fixed published weights) watches BTC market data and posts risk
scores to a SignalOracle contract on Base Sepolia. A reactive contract on
Reactive Lasna subscribes to those signals. When the score crosses −30, the
guardian requests a callback that makes the GuardianVault on Base Sepolia move
100% of user deposits into a segregated SafeBucket contract; when the score
recovers past +20, a second callback moves everything back. Users set the
thresholds once and never think about it again — the loop runs entirely
on-chain, and both legs (signal → reaction, reaction → callback) are visible
in the explorers.

Why it matters: stop-loss protection today means trusting an off-chain bot
with a hot key, or not having protection at all. Sentinel replaces the bot
with a reactive contract: the decision logic is public, the triggers are
on-chain events, and the vault only accepts orders that arrive through the
Reactive callback proxy from the one authorised guardian contract.

**What to verify (judges):**
- Repository: (public GitHub link — added at submission)
- Contracts: see deployments.json in the repo
  - SignalOracle (Base Sepolia), SentimentGuardian (Lasna), GuardianVault +
    SafeBucket (Base Sepolia)
- Full-loop tx hashes: see demo-evidence/ in the repo (signal tx → reactive
  tx on Lasna → callback tx on Base Sepolia, with measured timings)
- Demo video: under 3 minutes (link added at submission)
- Local proof: `forge test` runs the whole protect/release loop against a
  faithful simulation of the system contract and callback proxy.

**Tech:** Solidity 0.8.29, Foundry, reactive-lib-omni (AbstractReactive /
AbstractCallback), Python 3 stdlib AI agent, Binance public market data.
