from dataclasses import dataclass
from typing import List, Tuple

# Standard EVM opcode gas costs (London/Shanghai specs)
GAS_TRANSACTION_BASE = 21_000
GAS_SSTORE_SET = 20_000        # Zero to non-zero storage write
GAS_SSTORE_RESET = 2_900       # Non-zero to non-zero storage write
GAS_SLOAD_COLD = 2_100         # First read of a storage slot
GAS_SLOAD_WARM = 100           # Subsequent reads of the same slot
GAS_MEMORY_COPY = 3            # In-memory variable assignment per word
GAS_CALLDATA_NONZERO = 16      # Calldata byte cost
GAS_CUSTOM_ERROR = 4 * 16      # 4-byte selector
GAS_REQUIRE_STRING = 32 * 16 + 68  # String revert payload


@dataclass
class GasTracker:
    total_gas: int = 0

    def consume(self, amount: int, label: str = "") -> None:
        self.total_gas += amount


class UnoptimizedSavingsVault:
    """
    Unoptimized Vault:
    - Separate uint256 storage slots (no packing)
    - Repeated SLOAD calls inside calculation loops (no memory cache)
    - Verbose require() error strings
    - Single-action transactions (no multicall batching)
    """

    def __init__(self):
        self.gas = GasTracker()

    def deposit(self, user_id: int, amount: int, initial_deposit: bool = True) -> int:
        start_gas = self.gas.total_gas
        self.gas.consume(GAS_TRANSACTION_BASE, "Base Tx")
        self.gas.consume(GAS_REQUIRE_STRING, "Require check string overhead")

        # Unpacked storage: 3 distinct uint256 slots
        # Slot 0: principal, Slot 1: deposit_timestamp, Slot 2: yield_index
        write_cost = GAS_SSTORE_SET if initial_deposit else GAS_SSTORE_RESET
        self.gas.consume(write_cost, "Slot 0: principal uint256")
        self.gas.consume(write_cost, "Slot 1: deposit_timestamp uint256")
        self.gas.consume(write_cost, "Slot 2: yield_index uint256")
        return self.gas.total_gas - start_gas

    def accrue_interest_loop(self, iterations: int) -> int:
        start_gas = self.gas.total_gas
        # Repeated SLOADs: reading state variable in each loop step
        self.gas.consume(GAS_SLOAD_COLD, "Cold SLOAD on vault state")
        for _ in range(iterations - 1):
            self.gas.consume(GAS_SLOAD_WARM, "Warm SLOAD on vault state")
        return self.gas.total_gas - start_gas


class OptimizedSparkSavingsVault:
    """
    Optimized Spark Savings Vault:
    - Packed struct: uint128 principal + uint64 timestamp + uint64 yield_index = 256 bits (1 slot)
    - Local memory caching for repeated storage reads
    - Custom error selectors instead of require strings
    - Batched multicall execution to amortize base transaction cost
    """

    def __init__(self):
        self.gas = GasTracker()

    def deposit(self, user_id: int, amount: int, initial_deposit: bool = True) -> int:
        start_gas = self.gas.total_gas
        self.gas.consume(GAS_TRANSACTION_BASE, "Base Tx")
        self.gas.consume(GAS_CUSTOM_ERROR, "Custom error signature check")

        # Storage packing: 3 fields fit into a single 32-byte slot
        write_cost = GAS_SSTORE_SET if initial_deposit else GAS_SSTORE_RESET
        self.gas.consume(write_cost, "Packed Slot: principal + timestamp + yield_index")
        return self.gas.total_gas - start_gas

    def accrue_interest_loop(self, iterations: int) -> int:
        start_gas = self.gas.total_gas
        # SLOAD caching: read once from storage, cache in memory word
        self.gas.consume(GAS_SLOAD_COLD, "Cold SLOAD into memory")
        for _ in range(iterations):
            self.gas.consume(GAS_MEMORY_COPY, "Memory read from local cache")
        return self.gas.total_gas - start_gas

    def batch_deposits(self, count: int) -> int:
        start_gas = self.gas.total_gas
        # Multicall: 1 base tx cost amortized across all operations
        self.gas.consume(GAS_TRANSACTION_BASE, "Single Base Tx for Batch")
        for _ in range(count):
            self.gas.consume(GAS_CUSTOM_ERROR, "Validation")
            self.gas.consume(GAS_SSTORE_RESET, "Single packed slot write")
        return self.gas.total_gas - start_gas


def run_comparison() -> None:
    unoptimized = UnoptimizedSavingsVault()
    optimized = OptimizedSparkSavingsVault()

    print("=" * 72)
    print("  SPARK SAVINGS: SMART CONTRACT GAS OPTIMIZATION BENCHMARK")
    print("=" * 72)

    # Scenario 1: Initial Deposit (Struct Packing vs Unpacked Slots)
    gas_unopt_dep = unoptimized.deposit(user_id=1, amount=1000, initial_deposit=True)
    gas_opt_dep = optimized.deposit(user_id=1, amount=1000, initial_deposit=True)
    diff_dep = gas_unopt_dep - gas_opt_dep
    pct_dep = (diff_dep / gas_unopt_dep) * 100

    print(f"\n[1] Initial Deposit (Storage Packing & Custom Errors)")
    print(f"    Unoptimized (3 slots + string require) : {gas_unopt_dep:,} gas")
    print(f"    Optimized Spark (1 slot packed + error): {gas_opt_dep:,} gas")
    print(f"    Gas Saved: {diff_dep:,} gas ({pct_dep:.1f}% reduction)")

    # Scenario 2: Loops & State Reads (Storage Caching in Memory)
    loops = 10
    gas_unopt_loop = unoptimized.accrue_interest_loop(iterations=loops)
    gas_opt_loop = optimized.accrue_interest_loop(iterations=loops)
    diff_loop = gas_unopt_loop - gas_opt_loop
    pct_loop = (diff_loop / gas_unopt_loop) * 100

    print(f"\n[2] Yield Calculation Loop ({loops} iterations - SLOAD vs Memory Cache)")
    print(f"    Unoptimized (Repeated SLOADs)          : {gas_unopt_loop:,} gas")
    print(f"    Optimized Spark (Cached in Memory)     : {gas_opt_loop:,} gas")
    print(f"    Gas Saved: {diff_loop:,} gas ({pct_loop:.1f}% reduction)")

    # Scenario 3: Batch Operations (Multicall Amortization)
    batch_size = 5
    gas_unopt_batch = sum(
        unoptimized.deposit(user_id=i, amount=500, initial_deposit=False)
        for i in range(batch_size)
    )
    gas_opt_batch = optimized.batch_deposits(count=batch_size)
    diff_batch = gas_unopt_batch - gas_opt_batch
    pct_batch = (diff_batch / gas_unopt_batch) * 100

    print(f"\n[3] Multiple Actions ({batch_size} consecutive deposits)")
    print(f"    Unoptimized ({batch_size} individual txs)         : {gas_unopt_batch:,} gas")
    print(f"    Optimized Spark (1 Multicall batch tx) : {gas_opt_batch:,} gas")
    print(f"    Gas Saved: {diff_batch:,} gas ({pct_batch:.1f}% reduction)")

    print("\n" + "=" * 72)
    total_unopt = gas_unopt_dep + gas_unopt_loop + gas_unopt_batch
    total_opt = gas_opt_dep + gas_opt_loop + gas_opt_batch
    total_diff = total_unopt - total_opt
    total_pct = (total_diff / total_unopt) * 100
    print(f"TOTAL GAS CONSUMPTION:")
    print(f"    Standard Vault        : {total_unopt:,} gas")
    print(f"    Optimized Spark Vault : {total_opt:,} gas")
    print(f"    Overall Savings       : {total_diff:,} gas ({total_pct:.1f}% saved)")
    print("=" * 72)


if __name__ == "__main__":
    run_comparison()
