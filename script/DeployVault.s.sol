// SPDX-License-Identifier: MIT
pragma solidity ^0.8.29;

import { Script } from "forge-std/Script.sol";
import { IPayable } from "@reactive/src/interfaces/IPayable.sol";
import { GuardianVault } from "../src/GuardianVault.sol";

/// @notice Deploys GuardianVault to Base Sepolia, funded with a little ETH so
///         it can pay the callback proxy. Env: GUARDIAN, MOCKUSD,
///         VAULT_FUND_WEI (optional).
contract DeployVault is Script {
    address internal constant BASE_SEPOLIA_PROXY = 0x476F44b11F5C942c58f4c8E3d0300E5710743585;

    function run() external {
        uint256 key = vm.envUint("PRIVATE_KEY");
        address guardian = vm.envAddress("GUARDIAN");
        address usd = vm.envAddress("MOCKUSD");
        uint256 fund = vm.envOr("VAULT_FUND_WEI", uint256(0.02 ether));
        vm.startBroadcast(key);
        GuardianVault vault = new GuardianVault{ value: fund }(
            IPayable(payable(BASE_SEPOLIA_PROXY)), guardian, usd
        );
        vm.stopBroadcast();
        vm.writeJson(
            vm.serializeAddress("deployment", "guardianVault", address(vault)),
            "./deployments-vault.json"
        );
        vm.writeJson(
            vm.serializeAddress("deployment", "safeBucket", address(vault.safeBucket())),
            "./deployments-vault.json"
        );
    }
}
