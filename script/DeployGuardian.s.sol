// SPDX-License-Identifier: MIT
pragma solidity ^0.8.29;

import { Script } from "forge-std/Script.sol";
import { SentimentGuardian } from "../src/SentimentGuardian.sol";

/// @notice Deploys SentimentGuardian to Reactive Lasna, funded with lREACT.
///         Env: ORACLE (SignalOracle address), GUARDIAN_FUND_WEI (optional).
contract DeployGuardian is Script {
    function run() external {
        uint256 key = vm.envUint("PRIVATE_KEY");
        address oracle = vm.envAddress("ORACLE");
        uint256 fund = vm.envOr("GUARDIAN_FUND_WEI", uint256(0.5 ether));
        vm.startBroadcast(key);
        SentimentGuardian guardian =
            new SentimentGuardian{ value: fund }(84532, oracle, 84532, -30, 20);
        vm.stopBroadcast();
        vm.writeJson(
            vm.serializeAddress("deployment", "sentimentGuardian", address(guardian)),
            "./deployments-guardian.json"
        );
    }
}
