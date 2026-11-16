// SPDX-License-Identifier: MIT
pragma solidity ^0.8.29;

import { Test } from "forge-std/Test.sol";
import { IReactive } from "@reactive/src/interfaces/IReactive.sol";
import { ISystemContract } from "@reactive/src/interfaces/ISystemContract.sol";
import { IPayable } from "@reactive/src/interfaces/IPayable.sol";
import { MockUSD } from "../src/MockUSD.sol";
import { SignalOracle } from "../src/SignalOracle.sol";
import { SentimentGuardian } from "../src/SentimentGuardian.sol";
import { GuardianVault } from "../src/GuardianVault.sol";

/// @notice Stand-in for the Reactive system contract, etched over the real
///         system address in tests. Records subscriptions and every callback
///         request so tests can inspect and "deliver" them like the network.
contract MockSystem {
    struct Req {
        uint256 chainId;
        address recipient;
        uint64 gasLimit;
        bytes payload;
    }

    Req[] public requests;
    uint256 public subscriptions;

    function subscribe(uint256, address, uint256, uint256, uint256, uint256) external {
        subscriptions += 1;
    }

    function unsubscribe(uint256, address, uint256, uint256, uint256, uint256) external {}

    function requestCallbackV_1_0(ISystemContract.CallbackConfiguration_V_1_0 memory cfg) external {
        requests.push(Req(cfg.chainId, cfg.recipient, cfg.gasLimit, cfg.payload));
    }

    function requestCallback(ISystemContract.CallbackVersion, bytes memory) external {}

    function debt(address) external pure returns (uint256) {
        return 0;
    }

    function requestCount() external view returns (uint256) {
        return requests.length;
    }

    function getRequest(uint256 i) external view returns (Req memory) {
        return requests[i];
    }
}

/// @notice Local end-to-end test of the whole Sentinel loop. On testnet the
///         system contract and callback proxy roles are played by Reactive
///         Network itself; here they are simulated faithfully (including the
///         proxy overwriting the payload's first argument with the guardian's
///         address before delivery).
contract SentinelTest is Test {
    address internal constant SYSTEM = 0x8888888888888888888888888888888888888888;
    address internal constant PROXY = 0x476F44b11F5C942c58f4c8E3d0300E5710743585;
    uint256 internal constant BASE_SEPOLIA = 84532;

    address internal agent = makeAddr("ai-agent");
    address internal user = makeAddr("user");
    address internal stranger = makeAddr("stranger");

    MockUSD internal usd;
    SignalOracle internal oracle;
    SentimentGuardian internal guardian;
    GuardianVault internal vault;
    MockSystem internal mockSystem;

    function setUp() public {
        MockSystem impl = new MockSystem();
        vm.etch(SYSTEM, address(impl).code);
        mockSystem = MockSystem(SYSTEM);

        usd = new MockUSD();
        oracle = new SignalOracle(agent);
        guardian = new SentimentGuardian{ value: 1 ether }(BASE_SEPOLIA, address(oracle), BASE_SEPOLIA, -30, 20);
        vault = new GuardianVault{ value: 0.1 ether }(
            IPayable(payable(PROXY)), address(guardian), address(usd)
        );
        guardian.setVault(address(vault));

        usd.mint(user, 10_000e6);
        vm.prank(user);
        usd.approve(address(vault), type(uint256).max);
    }

    function _log(int256 score, uint256 confidence) internal view returns (IReactive.LogRecord memory log_) {
        log_.chainId = BASE_SEPOLIA;
        log_.contractAddress = address(oracle);
        log_.topic0 = uint256(keccak256("SignalPosted(int256,uint256,uint256,uint256)"));
        log_.data = abi.encode(score, confidence, uint256(1_700_000_000), uint256(1));
        log_.blockNumber = 12345;
        log_.opCode = 1;
    }

    /// @dev Emulates the Reactive callback proxy: overwrite the payload's
    ///      first argument (bytes 4..36) with the requesting contract's
    ///      address, then deliver the call from the proxy's address.
    function _deliver(uint256 requestIdx, address reactiveSender) internal {
        MockSystem.Req memory req = mockSystem.getRequest(requestIdx);
        bytes memory payload = req.payload;
        bytes20 senderBytes = bytes20(reactiveSender);
        for (uint256 i = 0; i < 20; i++) {
            payload[4 + 12 + i] = senderBytes[i];
        }
        vm.prank(PROXY);
        (bool ok, bytes memory ret) = req.recipient.call(payload);
        if (!ok) {
            assembly {
                revert(add(ret, 32), mload(ret))
            }
        }
    }

    function test_oracle_onlyAgentPosts() public {
        vm.prank(stranger);
        vm.expectRevert(SignalOracle.NotAgent.selector);
        oracle.postSignal(-50, 90);

        vm.prank(agent);
        oracle.postSignal(-50, 90);
        assertEq(oracle.latestScore(), -50);
        assertEq(oracle.seq(), 1);
    }

    function test_guardian_subscribedOnDeploy() public view {
        assertEq(mockSystem.subscriptions(), 1);
    }

    function test_guardian_ignoresStrangersAndCalmSignals() public {
        // react() from anyone but the system contract reverts.
        vm.expectRevert();
        guardian.react(_log(-80, 90));

        // A calm signal is recorded but triggers no callback.
        vm.prank(SYSTEM);
        guardian.react(_log(10, 50));
        assertEq(guardian.signalsSeen(), 1);
        assertEq(guardian.callbacksSent(), 0);
        assertFalse(guardian.protectionActive());
    }

    function test_fullLoop_protectAndRelease() public {
        // User deposits 1,000 mUSD into the vault.
        vm.prank(user);
        vault.deposit(1_000e6);
        assertEq(vault.riskyBalance(), 1_000e6);
        assertEq(vault.safeBalance(), 0);

        // AI posts a risk-off signal; the system delivers the log to Lasna.
        vm.prank(agent);
        oracle.postSignal(-64, 88);
        vm.prank(SYSTEM);
        guardian.react(_log(-64, 88));
        assertTrue(guardian.protectionActive());
        assertEq(mockSystem.requestCount(), 1);

        // The network delivers the callback to the vault on Base Sepolia.
        _deliver(0, address(guardian));
        assertTrue(vault.protectionActive());
        assertEq(vault.riskyBalance(), 0);
        assertEq(vault.safeBalance(), 1_000e6);

        // User can still withdraw while protected.
        vm.prank(user);
        vault.withdraw(400e6);
        assertEq(usd.balanceOf(user), 9_400e6);
        assertEq(vault.safeBalance(), 600e6);

        // Market recovers: risk-on signal runs the loop in reverse.
        vm.prank(SYSTEM);
        guardian.react(_log(42, 80));
        assertFalse(guardian.protectionActive());
        assertEq(mockSystem.requestCount(), 2);

        _deliver(1, address(guardian));
        assertFalse(vault.protectionActive());
        assertEq(vault.riskyBalance(), 600e6);
        assertEq(vault.safeBalance(), 0);
    }

    function test_vault_rejectsForgedCallbacks() public {
        // Right sender address, wrong caller (not the proxy).
        vm.prank(stranger);
        vm.expectRevert();
        vault.onRiskAlert(address(guardian), -90);

        // Right caller (the proxy), wrong reactive sender.
        vm.prank(PROXY);
        vm.expectRevert();
        vault.onRiskAlert(stranger, -90);
    }
}
