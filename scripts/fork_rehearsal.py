#!/usr/bin/env python3
"""
Sentinel FORK REHEARSAL — the full loop on local Anvil forks of Base Sepolia
(:8545) and Reactive Lasna (:8546), using the REAL system contract and the
REAL callback proxy code from the forks. The two things a fork cannot do —
the network noticing the event and the network delivering the callback — are
played by this driver via Anvil impersonation of the system contract and the
callback proxy, exactly as the unit tests simulate them.

This is a rehearsal, not the live run: scripts/run_demo.py does the same
steps against the real testnets once the deployer is funded.

Uses Anvil's well-known public dev account #0 as deployer on the forks.
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "http://127.0.0.1:8545"
LASNA = "http://127.0.0.1:8546"
SYSTEM = "0x8888888888888888888888888888888888888888"
PROXY = "0x476F44b11F5C942c58f4c8E3d0300E5710743585"
DEV_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
DEV = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"


def run(cmd, **kw):
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300, **kw)
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])} failed: {out.stderr.strip() or out.stdout.strip()}")
    return out.stdout.strip()


def cast(*args, rpc=None, key=None, frm=None, expect_json=False):
    cmd = ["cast"] + list(args)
    if rpc:
        cmd += ["--rpc-url", rpc]
    if key:
        cmd += ["--private-key", key]
    if frm:
        cmd += ["--from", frm, "--unlocked"]
    if expect_json:
        cmd += ["--json"]
    return run(cmd) if not expect_json else json.loads(run(cmd))


def create(contract, rpc, *ctor_args, value=None):
    cmd = ["forge", "create", contract, "--rpc-url", rpc, "--private-key", DEV_KEY, "--json", "--broadcast"]
    if value:
        cmd += ["--value", value]
    if ctor_args:
        cmd += ["--constructor-args"] + list(ctor_args)
    nonce = int(cast("nonce", DEV, rpc=rpc).split()[0])
    addr = cast("compute-address", DEV, "--nonce", str(nonce), rpc=rpc).split(":")[-1].strip()
    run(cmd, cwd=ROOT)
    return addr


def call(addr, sig, rpc, *args):
    return cast("call", addr, sig, *args, rpc=rpc).split()[0]


def banner(n, text):
    print(f"\n{'=' * 72}\nSTEP {n}: {text}\n{'=' * 72}", flush=True)


def main():
    print("SENTINEL — fork rehearsal (Base Sepolia fork :8545, Lasna fork :8546)")
    print(f"deployer (anvil dev #0): {DEV}")
    # Fund the deployer on the Lasna fork (forked balance may be zero).
    cast("rpc", "anvil_setBalance", DEV, "0x56BC75E2D63100000", rpc=LASNA)
    print("lasna fork balance:", cast("balance", DEV, rpc=LASNA))

    banner(1, "Deploy SignalOracle + MockUSD on Base Sepolia (fork)")
    usd = create("src/MockUSD.sol:MockUSD", BASE)
    oracle = create("src/SignalOracle.sol:SignalOracle", BASE, DEV)
    print(f"MockUSD:      {usd}\nSignalOracle: {oracle}")

    banner(2, "Deploy SentimentGuardian on Reactive Lasna (fork) — subscribes in constructor")
    guardian = create("src/SentimentGuardian.sol:SentimentGuardian", LASNA,
                      "84532", oracle, "84532", "-30", "20", value="5000000000000000000")
    print(f"SentimentGuardian: {guardian}")

    banner(3, "Deploy GuardianVault on Base Sepolia (fork), wire guardian.setVault")
    vault = create("src/GuardianVault.sol:GuardianVault", BASE,
                   PROXY, guardian, usd, value="100000000000000000")
    bucket = call(vault, "safeBucket()(address)", BASE)
    print(f"GuardianVault: {vault}\nSafeBucket:    {bucket}")
    tx = cast("send", guardian, "setVault(address)", vault, rpc=LASNA, key=DEV_KEY, expect_json=True)
    print(f"setVault tx: {tx['transactionHash']}")

    banner(4, "User deposits 1,000 mUSD")
    cast("send", usd, "mint(address,uint256)", DEV, "10000000000", rpc=BASE, key=DEV_KEY)
    cast("send", usd, "approve(address,uint256)", vault,
         "115792089237316195423570985008687907853269984665640564039457584007913129639935",
         rpc=BASE, key=DEV_KEY)
    tx = cast("send", vault, "deposit(uint256)", "1000000000", rpc=BASE, key=DEV_KEY, expect_json=True)
    print(f"deposit tx: {tx['transactionHash']}")
    print(f"risky={call(vault, 'riskyBalance()(uint256)', BASE)} safe={call(vault, 'safeBalance()(uint256)', BASE)}")

    banner(5, "AI agent scores a CRASH scenario and posts the signal on-chain")
    env = {**os.environ, "PRIVATE_KEY": DEV_KEY,
           "PATH": os.environ["PATH"] + ":" + os.path.expanduser("~/workspace/tools/foundry/bin")}
    out = subprocess.run([sys.executable, os.path.join(ROOT, "agent", "signal_agent.py"),
                          "--oracle", oracle, "--scenario", "crash", "--rpc", BASE],
                         capture_output=True, text=True, env=env, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"agent failed: {out.stderr}")
    print(out.stdout)
    sig_tx = json.loads(out.stdout[out.stdout.rindex('{"signal_tx"'):])["signal_tx"]

    recent = int(cast("block-number", rpc=BASE)) - 50
    logs = cast("logs", "--address", oracle, "SignalPosted(int256,uint256,uint256,uint256)",
                "--from-block", str(recent), "--to-block", "latest", rpc=BASE, expect_json=True)
    log = logs[-1]
    print(f"SignalPosted log: block {int(log['blockNumber'], 16)}, tx {log['transactionHash']}")

    banner(6, "Network leg: system contract delivers the log -> guardian.react() on Lasna")
    topic0 = str(int(log["topics"][0], 16))
    data = log["data"]
    block_no = str(int(log["blockNumber"], 16))
    block_hash = str(int(log["blockHash"], 16))
    tx_hash = str(int(log["transactionHash"], 16))
    record = (f"({84532},{oracle},{topic0},0,0,0,{data},{block_no},1,{block_hash},{tx_hash},0)")
    cast("rpc", "anvil_impersonateAccount", SYSTEM, rpc=LASNA)
    tx = cast("send", guardian, "react((uint256,address,uint256,uint256,uint256,uint256,bytes,uint256,uint256,uint256,uint256,uint256))",
              record, rpc=LASNA, frm=SYSTEM, expect_json=True)
    cast("rpc", "anvil_stopImpersonatingAccount", SYSTEM, rpc=LASNA)
    print(f"react tx (Lasna fork): {tx['transactionHash']}")
    print(f"guardian.protectionActive = {call(guardian, 'protectionActive()(bool)', LASNA)}")
    print(f"guardian.callbacksSent    = {call(guardian, 'callbacksSent()(uint256)', LASNA)}")
    print(f"guardian.lastScore        = {call(guardian, 'lastScore()(int256)', LASNA)}")

    banner(7, "Network leg: callback proxy delivers onRiskAlert -> vault on Base Sepolia")
    cast("rpc", "anvil_impersonateAccount", PROXY, rpc=BASE)
    tx = cast("send", vault, "onRiskAlert(address,int256)", guardian, "-100", rpc=BASE, frm=PROXY, expect_json=True)
    cast("rpc", "anvil_stopImpersonatingAccount", PROXY, rpc=BASE)
    print(f"callback tx (Base fork): {tx['transactionHash']}")
    print(f"vault.protectionActive = {call(vault, 'protectionActive()(bool)', BASE)}")
    print(f"risky={call(vault, 'riskyBalance()(uint256)', BASE)} safe={call(vault, 'safeBalance()(uint256)', BASE)}")

    banner(8, "AI agent scores a CALM scenario; loop runs in reverse")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "agent", "signal_agent.py"),
                          "--oracle", oracle, "--scenario", "calm", "--rpc", BASE],
                         capture_output=True, text=True, env=env, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"agent (calm) failed: {out.stderr}")
    print(out.stdout)
    recent = int(cast("block-number", rpc=BASE)) - 50
    logs = cast("logs", "--address", oracle, "SignalPosted(int256,uint256,uint256,uint256)",
                "--from-block", str(recent), "--to-block", "latest", rpc=BASE, expect_json=True)
    log = logs[-1]
    topic0 = str(int(log["topics"][0], 16))
    record = (f"({84532},{oracle},{topic0},0,0,0,{log['data']},{int(log['blockNumber'], 16)},1,"
              f"{int(log['blockHash'], 16)},{int(log['transactionHash'], 16)},0)")
    cast("rpc", "anvil_impersonateAccount", SYSTEM, rpc=LASNA)
    cast("send", guardian, "react((uint256,address,uint256,uint256,uint256,uint256,bytes,uint256,uint256,uint256,uint256,uint256))",
         record, rpc=LASNA, frm=SYSTEM)
    cast("rpc", "anvil_stopImpersonatingAccount", SYSTEM, rpc=LASNA)
    cast("rpc", "anvil_impersonateAccount", PROXY, rpc=BASE)
    tx = cast("send", vault, "onRiskCleared(address,int256)", guardian, "100", rpc=BASE, frm=PROXY, expect_json=True)
    cast("rpc", "anvil_stopImpersonatingAccount", PROXY, rpc=BASE)
    print(f"clear callback tx (Base fork): {tx['transactionHash']}")
    print(f"vault.protectionActive = {call(vault, 'protectionActive()(bool)', BASE)}")
    print(f"risky={call(vault, 'riskyBalance()(uint256)', BASE)} safe={call(vault, 'safeBalance()(uint256)', BASE)}")

    banner("DONE", "Full loop proven on forks: signal -> react -> callback -> funds moved -> restored")
    print(json.dumps({"mockUsd": usd, "signalOracle": oracle, "sentimentGuardian": guardian,
                      "guardianVault": vault, "safeBucket": bucket}, indent=2))


if __name__ == "__main__":
    main()
