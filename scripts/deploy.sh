#!/usr/bin/env bash
# Deploys the full Sentinel stack:
#   1. MockUSD + SignalOracle      -> Base Sepolia
#   2. SentimentGuardian (funded)  -> Reactive Lasna
#   3. GuardianVault (funded)      -> Base Sepolia
#   4. guardian.setVault(vault)    -> Lasna wiring
# Requires PRIVATE_KEY in env (a testnet-only burner). Writes deployments.json.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${PRIVATE_KEY:?set PRIVATE_KEY}"
export PRIVATE_KEY
BASE=https://sepolia.base.org
LASNA=https://lasna-rpc.rnk.dev/

forge script script/DeployOrigin.s.sol --rpc-url $BASE --broadcast --slow
export ORACLE=$(python3 -c "import json;print(json.load(open('deployments-origin.json'))['signalOracle'])")
export MOCKUSD=$(python3 -c "import json;print(json.load(open('deployments-origin.json'))['mockUsd'])")

forge script script/DeployGuardian.s.sol --rpc-url $LASNA --broadcast --slow
export GUARDIAN=$(python3 -c "import json;print(json.load(open('deployments-guardian.json'))['sentimentGuardian'])")

forge script script/DeployVault.s.sol --rpc-url $BASE --broadcast --slow
VAULT=$(python3 -c "import json;print(json.load(open('deployments-vault.json'))['guardianVault'])")
BUCKET=$(python3 -c "import json;print(json.load(open('deployments-vault.json'))['safeBucket'])")

cast send "$GUARDIAN" "setVault(address)" "$VAULT" --rpc-url $LASNA --private-key "$PRIVATE_KEY" >/dev/null
echo "wired: guardian.setVault($VAULT)"

python3 - "$MOCKUSD" "$ORACLE" "$GUARDIAN" "$VAULT" "$BUCKET" <<'PY'
import json, sys
mock, oracle, guardian, vault, bucket = sys.argv[1:6]
json.dump({
    "baseSepolia": {"chainId": 84532, "mockUsd": mock, "signalOracle": oracle,
                    "guardianVault": vault, "safeBucket": bucket},
    "lasna": {"chainId": 5318007, "sentimentGuardian": guardian},
}, open("deployments.json", "w"), indent=2)
print(open("deployments.json").read())
PY
