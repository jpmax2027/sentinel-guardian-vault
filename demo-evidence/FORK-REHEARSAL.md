# Sentinel — fork rehearsal evidence

**What this is:** the complete Sentinel loop executed on local Anvil forks of
Base Sepolia and Reactive Lasna, using the *real* system-contract and
callback-proxy code from those chains. The two legs only the live network can
perform — noticing the event and delivering the callback — were played by the
driver via Anvil impersonation of the system contract (`0x8888…8888`) and the
callback proxy (`0x476F…3585`), the same simulation the unit tests use.

**What this is not:** the live testnet run. That run (`scripts/run_demo.py`,
same steps, real chains) needs the deployer funded with Base Sepolia ETH +
lREACT — see the project README "Setup & run". Everything else (contracts,
agent, deploy scripts, demo script) is identical between the two runs.

Full terminal log: `fork-rehearsal.log` (this directory).

## Result summary (from the log)

- Stack deployed on the forks; guardian's constructor subscription against
  the real Lasna system contract succeeded.
- Deposit: 1,000 mUSD into the vault (risky = 1,000,000,000 units, safe = 0).
- AI agent, CRASH scenario: score **−100** (confidence 100) → `SignalPosted`.
- `react()` delivered as the system contract: guardian `protectionActive =
  true`, `callbacksSent = 1`, `lastScore = −100`; the guardian's
  `requestCallbackV_1_0` call to the real system contract succeeded.
- Callback delivered as the proxy: vault `onRiskAlert` → **risky = 0, safe =
  1,000,000,000** (all funds in the SafeBucket).
- AI agent, CALM scenario: score **+100** → `react()` → `onRiskCleared` →
  **risky = 1,000,000,000, safe = 0** (funds restored).

Unit tests (`forge test`, 5/5) cover the same loop plus forged-callback
rejection and withdraw-during-protection.
