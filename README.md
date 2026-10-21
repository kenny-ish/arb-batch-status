# arb-batch-status

Tells you where an Arbitrum block or transaction stands on its way to L1: which sequencer batch contains it, how many L1 confirmations that batch has, and whether the block is below the node's `safe` and `finalized` heads. Useful when a transaction shows as confirmed on L2 but you need to know if it is already posted to Ethereum before trusting it. It only talks to the Arbitrum JSON-RPC, using `eth_call` against the NodeInterface virtual contract (`0x...C8`). No external packages.

## Example

Arbitrum One, run on 2026-10-10:

```
$ python arb_batch_status.py --rpc https://arb1.arbitrum.io/rpc --block 513466368
L2 block:          513466368
block hash:        0xfa7f4037b7033e4da3121ca512f7a4b9e95d23924445d187a3364542bd2ede3d
L2 timestamp:      1791622564
L1 origin block:   26160974
batch:             1353808
L1 confirmations:  95
latest head:       513470687 (block is 4319 below)
safe head:         513468584 (block is 2216 below)
finalized head:    513467218 (block is 850 below)
status:            FINALIZED (batch is in a finalized L1 block, at or below the finalized head)
```

A block that is only in the sequencer feed so far:

```
$ python arb_batch_status.py --rpc https://arb1.arbitrum.io/rpc --block 513470693
L2 block:          513470693
block hash:        0x24f8dc7ebef1571ea6a20bf9e1cca6907bc836555a381622fa5e4cffcdfebdf6
L2 timestamp:      1791623754
L1 origin block:   26161073
batch:             none yet
L1 confirmations:  0
latest head:       513470695 (block is 2 below)
safe head:         513468584 (block is 2109 above)
finalized head:    513467218 (block is 3475 above)
status:            NOT_POSTED (only in the sequencer feed, no batch on L1 yet)
```

By transaction hash, as JSON:

```
$ python arb_batch_status.py --rpc https://arb1.arbitrum.io/rpc \
    --tx 0x4f6a49e57da3042ec40605815f4817084bcec43d486b62ab865b368b339d3489 --json
{
  "block_number": 513466368,
  "block_hash": "0xfa7f4037b7033e4da3121ca512f7a4b9e95d23924445d187a3364542bd2ede3d",
  "timestamp": 1791622564,
  "l1_origin_block": 26160974,
  "batch": 1353808,
  "l1_confirmations": 95,
  "latest_head": 513470691,
  "safe_head": 513468584,
  "finalized_head": 513467218,
  "status": "FINALIZED",
  "tx_hash": "0x4f6a49e57da3042ec40605815f4817084bcec43d486b62ab865b368b339d3489",
  "tx_index": 1
}
```

## Usage

```
python arb_batch_status.py --rpc URL --block N [--json]
python arb_batch_status.py --rpc URL --tx HASH [--json]
```

- `--rpc` Arbitrum Nitro JSON-RPC URL (Arbitrum One, Nova, or any Orbit chain).
- `--block` L2 block number, or `--tx` L2 transaction hash (the receipt gives the block).
- `--json` machine-readable output.

Exit code is 0 when the block is in a batch on L1, 2 when it is not posted yet, 1 on error.

Status values:

- `NOT_POSTED` NodeInterface does not know a batch for the block yet.
- `POSTED` a batch exists but the node's `safe` head is still below the block.
- `SAFE` block is at or below the `safe` head.
- `FINALIZED` block is at or below the `finalized` head.

The `safe` and `finalized` tags are whatever the node reports; on some public endpoints they lag behind the confirmation count, so read both.

## How it works

1. `eth_getBlockByNumber` for the block (or `eth_getTransactionReceipt` first when `--tx` is used) and for the `latest`, `safe` and `finalized` tags. Nitro headers carry `l1BlockNumber`, the L1 block the sequencer used as origin.
2. `eth_call` to NodeInterface `findBatchContainingBlock(uint64)` (selector `0x81f1adaf`). A revert means the block is not in any posted batch.
3. `eth_call` to NodeInterface `getL1Confirmations(bytes32 blockHash)` (selector `0xe5ca238c`) for the number of L1 blocks on top of the batch.
4. Combines the batch result with the safe and finalized heads into one status.

Selectors are computed with a small keccak-256 implementation in the file (`hashlib.sha3_256` is not keccak).

## Tests

```
python -m unittest -v
```

Tests run offline against recorded RPC responses for Arbitrum One block 513466368 (batch 1353808) and check calldata encoding, revert handling and the status logic.
