#!/usr/bin/env python3
"""
Sentinel AI signal agent.

A small, fully transparent scoring model that watches BTC/USDT market data and
posts a risk score to the SignalOracle contract on Base Sepolia. The reactive
contract on Lasna does the rest — this agent never touches the vault.

Model (fixed weights, no hidden state — see MODEL_CARD in README.md):
  features from 48 hourly candles
    ret24    24h return
    mom      EMA(12)/EMA(26) - 1          (trend)
    rsi      RSI(14)                       (mean reversion / exhaustion)
    vol      stdev of hourly log returns * sqrt(24)   (realised daily vol)
  score = clamp( 1200*ret24 + 1800*mom + 0.7*(rsi-50) - vol_drag , -100, 100)
  vol_drag = min(25, max(0, (vol - 0.025)) * 800)
  confidence grows with |score| and with feature agreement.

Scenarios:
  live   score the real market right now (default)
  crash  append 8 synthetic -3.2%/h candles to the live series, then score
         (stress-test: proves the protection path end-to-end on demand)
  calm   append 8 synthetic +2.2%/h candles, then score (proves the release)

Usage:
  PRIVATE_KEY=0x... python3 signal_agent.py --oracle 0x... [--scenario crash]
  python3 signal_agent.py --dry-run [--scenario crash]     # score only, no tx
"""
import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import urllib.request

KLINE_ENDPOINTS = [
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.com/api/v3/klines",
]
BASE_SEPOLIA_RPC = "https://sepolia.base.org"


def fetch_closes(symbol="BTCUSDT", interval="1h", limit=48):
    last_err = None
    for base in KLINE_ENDPOINTS:
        url = f"{base}?symbol={symbol}&interval={interval}&limit={limit}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sentinel-agent/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode())
            return [float(k[4]) for k in data]  # close prices
        except Exception as e:  # noqa: BLE001 - try next mirror
            last_err = e
    raise RuntimeError(f"could not fetch klines: {last_err}")


def apply_scenario(closes, scenario):
    if scenario == "live":
        return closes
    step = -0.032 if scenario == "crash" else 0.022
    out = list(closes)
    for _ in range(8):
        out.append(out[-1] * (1 + step))
    return out


def ema(values, period):
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes, period=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = statistics.mean(gains[-period:])
    avg_loss = statistics.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def score_market(closes):
    ret24 = closes[-1] / closes[-25] - 1
    mom = ema(closes, 12) / ema(closes, 26) - 1
    r = rsi(closes)
    logrets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    vol = statistics.pstdev(logrets) * math.sqrt(24)

    parts = {
        "ret24": 1200 * ret24,
        "momentum": 1800 * mom,
        "rsi": 0.7 * (r - 50),
        "vol_drag": -min(25.0, max(0.0, (vol - 0.025)) * 800),
    }
    raw = sum(parts.values())
    score = int(max(-100, min(100, round(raw))))

    signs = [1 if v > 0 else -1 if v < 0 else 0 for k, v in parts.items() if k != "vol_drag"]
    if score != 0:
        agree = sum(1 for s in signs if s == (1 if score > 0 else -1)) / len(signs)
    else:
        agree = 0.0
    confidence = int(max(0, min(100, 35 + abs(score) * 0.55 + agree * 10)))

    return {
        "score": score,
        "confidence": confidence,
        "features": {
            "ret24_pct": round(ret24 * 100, 3),
            "momentum_pct": round(mom * 100, 3),
            "rsi": round(r, 2),
            "daily_vol_pct": round(vol * 100, 3),
        },
        "contributions": {k: round(v, 2) for k, v in parts.items()},
    }


def post_signal(oracle, score, confidence, key, rpc):
    cmd = [
        "cast", "send", oracle,
        "postSignal(int256,uint256)", str(score), str(confidence),
        "--rpc-url", rpc, "--private-key", key, "--json",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"cast send failed: {out.stderr.strip()}")
    receipt = json.loads(out.stdout)
    return receipt["transactionHash"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oracle", default=os.environ.get("ORACLE_ADDRESS", ""))
    ap.add_argument("--scenario", choices=["live", "crash", "calm"], default="live")
    ap.add_argument("--rpc", default=BASE_SEPOLIA_RPC)
    ap.add_argument("--key-file", default=os.environ.get("PRIVATE_KEY_FILE", ""))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    closes = apply_scenario(fetch_closes(), args.scenario)
    result = score_market(closes)
    result["scenario"] = args.scenario
    result["candles_used"] = len(closes)
    print(json.dumps(result, indent=2))

    if args.dry_run:
        return
    if not args.oracle:
        sys.exit("error: --oracle or ORACLE_ADDRESS required")

    key = os.environ.get("PRIVATE_KEY", "")
    if not key and args.key_file:
        with open(args.key_file) as f:
            key = f.read().strip()
    if not key:
        sys.exit("error: PRIVATE_KEY env or --key-file required")

    tx = post_signal(args.oracle, result["score"], result["confidence"], key, args.rpc)
    print(json.dumps({"signal_tx": tx}))


if __name__ == "__main__":
    main()
