#!/usr/bin/env python3
"""
Sentinel live demo runner (Base Sepolia + Reactive Lasna testnets).

  1. Mint MockUSD, deposit 1,000 into the GuardianVault.
  2. AI agent scores a CRASH scenario and posts the signal on-chain.
  3. Wait for the guardian on Lasna to react, then for the callback to land
     on Base Sepolia and move the funds into the SafeBucket. Times both legs.
  4. AI agent scores a CALM scenario; the loop runs in reverse.
  5. Writes a Markdown evidence file with every tx hash and timing.

Key: PRIVATE_KEY env, or ../../hidden/burner-key.txt relative to this repo.
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://sepolia.base.org"
LASNA = "https://lasna-rpc.rnk.dev/"
TIMEOUT = 240


def cast(*args, rpc=None, key=None, expect_json=False):
    cmd = ["cast"] + list(args)
    if rpc:
        cmd += ["--rpc-url", rpc]
    if key:
        cmd += ["--private-key", key]
    if expect_json:
        cmd += ["--json"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        raise RuntimeError(f"cast {' '.join(args[:3])} failed: {out.stderr.strip()}")
    return json.loads(out.stdout) if expect_json else out.stdout.strip()


def call(addr, sig, rpc, *args):
    return cast("call", addr, sig, *args, rpc=rpc).split()[0]


def wait_until(label, fn, timeout=TIMEOUT, interval=3):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fn():
            return time.time() - t0
        time.sleep(interval)
    raise TimeoutError(f"timed out waiting for {label}")


def find_event_tx(addr, sig, rpc, from_block):
    logs = cast("logs", "--address", addr, sig, "--from-block", str(from_block),
                "--to-block", "latest", rpc=rpc, expect_json=True)
    if not logs:
        return None
    return logs[-1]["transactionHash"]


def main():
    dep = json.load(open(os.path.join(ROOT, "deployments.json")))
    usd = dep["baseSepolia"]["mockUsd"]
    oracle = dep["baseSepolia"]["signalOracle"]
    vault = dep["baseSepolia"]["guardianVault"]
    guardian = dep["lasna"]["sentimentGuardian"]

    key = os.environ.get("PRIVATE_KEY", "")
    if not key:
        with open(os.path.join(ROOT, "..", "hidden", "burner-key.txt")) as f:
            key = f.read().strip()
    me = cast("wallet", "address", "--private-key", key)

    ev = {"deployer": me, "steps": []}
    print(f"== Sentinel demo, deployer {me}")

    # 1. Fund + deposit
    tx = cast("send", usd, "mint(address,uint256)", me, "10000000000", rpc=BASE, key=key, expect_json=True)
    ev["steps"].append(("mint 10,000 mUSD", tx["transactionHash"]))
    cast("send", usd, "approve(address,uint256)", vault,
         "115792089237316195423570985008687907853269984665640564039457584007913129639935",
         rpc=BASE, key=key)
    tx = cast("send", vault, "deposit(uint256)", "1000000000", rpc=BASE, key=key, expect_json=True)
    ev["steps"].append(("deposit 1,000 mUSD into vault", tx["transactionHash"]))
    print(f"deposited. risky={call(vault, 'riskyBalance()(uint256)', BASE)} safe={call(vault, 'safeBalance()(uint256)', BASE)}")

    # 2. Crash signal
    base_block = int(cast("block-number", rpc=BASE))
    t_signal = time.time()
    agent = subprocess.run(
        [sys.executable, os.path.join(ROOT, "agent", "signal_agent.py"),
         "--oracle", oracle, "--scenario", "crash"],
        capture_output=True, text=True, env={**os.environ, "PRIVATE_KEY": key}, timeout=300)
    if agent.returncode != 0:
        raise RuntimeError(f"agent failed: {agent.stderr}")
    agent_out = json.loads(agent.stdout[: agent.stdout.rindex("}") + 1]) if False else None
    # agent prints two JSON objects; parse the last one for the tx
    txt = agent.stdout
    sig_tx = json.loads(txt[txt.rindex('{"signal_tx"'):])["signal_tx"]
    score_obj = json.loads(txt[: txt.index('{"signal_tx"')].strip())
    ev["crash_score"] = score_obj
    ev["steps"].append((f"AI posts CRASH signal (score {score_obj['score']})", sig_tx))
    print(f"crash signal posted: {sig_tx} score={score_obj['score']}")

    # 3. Wait for the loop
    dt = wait_until("guardian protectionActive",
                    lambda: call(guardian, "protectionActive()(bool)", LASNA) == "true")
    ev["guardian_reacted_after_s"] = round(dt, 1)
    print(f"guardian reacted after {dt:.1f}s")
    dt = wait_until("vault protectionActive",
                    lambda: call(vault, "protectionActive()(bool)", BASE) == "true")
    ev["callback_landed_after_s"] = round(time.time() - t_signal, 1)
    print(f"callback landed; total loop {ev['callback_landed_after_s']}s")
    cb_tx = find_event_tx(vault, "Protected(int256,uint256)", BASE, base_block)
    ev["steps"].append(("Reactive callback: vault Protected (funds -> SafeBucket)", cb_tx))
    ev["protected_state"] = {
        "risky": call(vault, "riskyBalance()(uint256)", BASE),
        "safe": call(vault, "safeBalance()(uint256)", BASE),
    }
    print(f"protected state: {ev['protected_state']}")

    # 4. Calm signal -> release
    base_block = int(cast("block-number", rpc=BASE))
    agent = subprocess.run(
        [sys.executable, os.path.join(ROOT, "agent", "signal_agent.py"),
         "--oracle", oracle, "--scenario", "calm"],
        capture_output=True, text=True, env={**os.environ, "PRIVATE_KEY": key}, timeout=300)
    if agent.returncode != 0:
        raise RuntimeError(f"agent (calm) failed: {agent.stderr}")
    txt = agent.stdout
    sig_tx2 = json.loads(txt[txt.rindex('{"signal_tx"'):])["signal_tx"]
    score_obj2 = json.loads(txt[: txt.index('{"signal_tx"')].strip())
    ev["calm_score"] = score_obj2
    ev["steps"].append((f"AI posts CALM signal (score {score_obj2['score']})", sig_tx2))
    wait_until("vault cleared", lambda: call(vault, "protectionActive()(bool)", BASE) == "false")
    cb_tx2 = find_event_tx(vault, "ProtectionCleared(int256,uint256)", BASE, base_block)
    ev["steps"].append(("Reactive callback: vault ProtectionCleared (funds back)", cb_tx2))
    ev["final_state"] = {
        "risky": call(vault, "riskyBalance()(uint256)", BASE),
        "safe": call(vault, "safeBalance()(uint256)", BASE),
    }
    print(f"final state: {ev['final_state']}")

    # 5. Evidence file
    os.makedirs(os.path.join(ROOT, "demo-evidence"), exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(ROOT, "demo-evidence", f"evidence-{stamp}.md")
    with open(path, "w") as f:
        f.write("# Sentinel — live demo evidence\n\n")
        f.write(f"Deployer/agent: {me}\n\n")
        f.write("## Steps\n\n")
        for label, h in ev["steps"]:
            f.write(f"- {label}: `{h}`\n")
        f.write(f"\nGuardian reacted {ev.get('guardian_reacted_after_s')}s after the signal; "
                f"full loop (signal -> callback landed) {ev.get('callback_landed_after_s')}s.\n")
        f.write(f"\nProtected state: {ev.get('protected_state')}\n")
        f.write(f"Final state: {ev.get('final_state')}\n")
        f.write(f"\nCrash score detail: {json.dumps(ev.get('crash_score'))}\n")
        f.write(f"Calm score detail: {json.dumps(ev.get('calm_score'))}\n")
    print(f"evidence written: {path}")
    print(json.dumps(ev, indent=2))


if __name__ == "__main__":
    main()
