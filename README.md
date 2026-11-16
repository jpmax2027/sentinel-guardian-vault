# Sentinel — the AI-signal guardian vault

**Track: Reactive Meets AI** (also fits *Set It and Forget It*)
**Event:** Reactive Omni Buildathon (DoraHacks), Nov 5 – Dec 5, 2026

Sentinel protects a user's stablecoin position automatically. An AI agent scores
market risk from live price data and posts the score on-chain. A reactive
contract on Reactive Lasna watches those scores around the clock — no keeper,
no bot server, no human — and the moment the score crosses a risk-off
threshold, it orders the user's vault on Base Sepolia to move every token into
a segregated safe bucket. When the AI says the market has recovered, the funds
move back. Set the thresholds once; forget it.

## Why this needs Reactive

The protection decision has to happen *when the signal lands*, not when
someone's cron job next wakes up, and it has to span two chains: the signal
lives on Base Sepolia, the reaction is computed on Lasna, and the money moves
back on Base Sepolia. That event → react → callback loop is exactly what
Reactive contracts are. Remove Reactive and you are back to running a trusted
off-chain bot with a hot wallet — the thing this design exists to avoid.

## Architecture

```
 BTC/USDT market data (Binance public API)
        │
        ▼
 ┌────────────────┐   postSignal(score, confidence)   ┌──────────────────┐
 │  AI agent      │ ────────────────────────────────▶ │  SignalOracle    │
 │  (Python,      │        SignalPosted event         │  (Base Sepolia)  │
 │   scoring      │                                   └────────┬─────────┘
 │   model)       │                                            │ subscribed
 └────────────────┘                                            ▼
                                                      ┌──────────────────┐
                                                      │ SentimentGuardian│
                                                      │ (Reactive Lasna) │
                                                      │ react(): score ≤ │
                                                      │ -30 → protect;   │
                                                      │ score ≥ +20 →    │
                                                      │ release          │
                                                      └────────┬─────────┘
                                                callback       │
                                                (via proxy)    ▼
 ┌────────────────┐   deposit / withdraw   ┌──────────────────────────────┐
 │  User          │ ─────────────────────▶ │  GuardianVault (Base Sepolia)│
 │                  │ ◀───────────────────── │   ├─ risky allocation (vault)│
 └────────────────┘                        │   └─ safe allocation         │
                                           │       (SafeBucket contract)  │
                                           └──────────────────────────────┘
```

Contracts:

| Contract | Chain | Role |
|---|---|---|
| `SignalOracle` | Base Sepolia (84532) | On-chain inbox for AI signals. Only the authorised agent address can post. Emits `SignalPosted(score, confidence, postedAt, seq)`. |
| `SentimentGuardian` | Reactive Lasna (5318007) | `AbstractReactive`. Subscribes to `SignalPosted`; threshold logic in `react()`; requests callbacks via the system contract (`0x8888…8888`). |
| `GuardianVault` | Base Sepolia (84532) | `AbstractCallback`. Holds user deposits; on `onRiskAlert` moves all tokens to the SafeBucket, on `onRiskCleared` moves them back. Callbacks are double-authenticated: caller must be the Reactive callback proxy (`0x476F…3585`) **and** the injected sender must be the guardian. |
| `SafeBucket` | Base Sepolia | Segregated holding contract; only the vault can pull funds back out. |
| `MockUSD` | Base Sepolia | Faucet-mintable 6-decimal demo stablecoin, so the demo needs no real asset. |

## The AI model (MODEL CARD)

The agent (`agent/signal_agent.py`) is part of the running system — it is the
only entity that can post signals, and nothing reacts without it. It is a
small, fully transparent scoring model with fixed, published weights (no
hidden state, no API keys, ~150 lines of stdlib-only Python):

Features from 48 hourly BTC/USDT candles (Binance public data):

| Feature | Meaning |
|---|---|
| `ret24` | 24h return |
| `mom` | EMA(12)/EMA(26) − 1 (trend) |
| `rsi` | RSI(14) |
| `vol` | Realised daily volatility (stdev of hourly log returns × √24) |

`score = clamp(1200·ret24 + 1800·mom + 0.7·(rsi − 50) − vol_drag, −100, +100)`,
where `vol_drag = min(25, max(0, vol − 2.5%) × 800)` — high volatility drags the
score defensive even in a flat market. Confidence grows with |score| and with
agreement between feature signs.

Demo scenarios: `--scenario live` scores the real market; `--scenario crash`
appends 8 synthetic −3.2%/h candles to the live series (a stress test — the
model still computes the score from the data, which is how the protection path
is proven on demand); `--scenario calm` appends +2.2%/h candles to prove the
release path.

## Repository layout

```
src/            SignalOracle, SentimentGuardian, GuardianVault (+ SafeBucket), MockUSD
agent/          signal_agent.py — the AI agent (stdlib only)
script/         Foundry deploy scripts (origin / guardian / vault)
scripts/        deploy.sh (full stack), run_demo.py (live demo + evidence)
test/           Sentinel.t.sol — full-loop simulation incl. proxy emulation
demo-evidence/  Markdown evidence from live runs (tx hashes, timings)
deployments.json  Deployed addresses (filled in by scripts/deploy.sh)
```

## Note on dependencies

The GitHub copy of this repo omits the vendored `lib/` directory (Foundry
dependencies). To build locally, restore it first: clone `forge-std` into
`lib/forge-std` and the Reactive Network reactive contracts library into
`lib/reactive-lib` (see the remappings in `foundry.toml`), then run the setup
below. All project source, tests, scripts and deployment evidence are included.

## Setup & run

Prereqs: Foundry, Python 3. A testnet-only burner key in `PRIVATE_KEY`.

```bash
forge build && forge test        # 5 tests, incl. the full protect/release loop

# Fund the burner first (testnet only):
#   - Base Sepolia ETH (any public faucet), then
#   - lREACT: send a little Base Sepolia ETH to the Reactive faucet contract
#     0x2afaFD298b23b62760711756088F75B7409f5967 (1 ETH -> 100 lREACT)
export PRIVATE_KEY=0x...         # burner, testnet only
./scripts/deploy.sh              # deploys + wires everything, writes deployments.json

python3 scripts/run_demo.py      # deposit -> crash signal -> protected -> calm -> released
python3 agent/signal_agent.py --dry-run --scenario crash   # score only, no tx
```

## Deployed addresses & proof

**Status (2026-11-16):** contracts, AI agent, deploy scripts and demo script
are complete and rehearsed end-to-end. The full loop — deposit → crash signal
→ guardian reaction → callback → funds in the SafeBucket → calm signal →
funds restored — has been executed on local forks of Base Sepolia and Lasna
using the *real* system-contract and callback-proxy code (see
`demo-evidence/FORK-REHEARSAL.md` and `fork-rehearsal.log`; the two network
legs were played via impersonation, as in the unit tests).

The live testnet run (`scripts/deploy.sh` then `scripts/run_demo.py`, which
writes real addresses into `deployments.json` and real tx hashes into
`demo-evidence/`) is pending one thing only: funding the deployer with Base
Sepolia ETH (any account-gated public faucet) so it can deploy and swap a
little ETH for lREACT at the Reactive faucet contract. Everything after that
step is scripted and rehearsed.

**Demo video:** `demo-video.mp4` (2:24) — narrates the design and shows the
rehearsal results, labelled as such on screen.

Explorers: Base Sepolia — https://sepolia.basescan.org ·
Lasna — https://lasna.reactscan.net

## Safety notes

- Testnet only; every key here is a throwaway burner.
- The vault's callback handlers revert for any caller that is not the
  Reactive proxy, and for any reactive sender that is not the guardian
  (covered by tests). `react()` never reverts on foreign logs — it falls
  through, because a reverting reactive contract still gets billed.
- Users can withdraw during protection; the vault pulls their share back
  from the SafeBucket first.
