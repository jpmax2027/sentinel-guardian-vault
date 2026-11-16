// SPDX-License-Identifier: MIT
pragma solidity ^0.8.29;

import { Script } from "forge-std/Script.sol";
import { MockUSD } from "../src/MockUSD.sol";
import { SignalOracle } from "../src/SignalOracle.sol";

/// @notice Deploys MockUSD + SignalOracle to Base Sepolia.
///         The deployer is also the authorised AI agent address.
contract DeployOrigin is Script {
    function run() external {
        uint256 key = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(key);
        vm.startBroadcast(key);
        MockUSD usd = new MockUSD();
        SignalOracle oracle = new SignalOracle(deployer);
        vm.stopBroadcast();
        vm.writeJson(
            vm.serializeAddress("deployment", "mockUsd", address(usd)),
            "./deployments-origin.json"
        );
        vm.writeJson(
            vm.serializeAddress("deployment", "signalOracle", address(oracle)),
            "./deployments-origin.json"
        );
    }
}
