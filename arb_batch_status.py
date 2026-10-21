#!/usr/bin/env python3
"""Show where an Arbitrum (Nitro) block or transaction stands on the way to L1:
which sequencer batch holds it, how many L1 confirmations that batch has,
and whether the block is below the node's safe / finalized heads.

Uses only the Arbitrum JSON-RPC: eth_getBlockByNumber, eth_getTransactionReceipt
and eth_call against the NodeInterface virtual contract (0x...C8).
Python 3.10+, standard library only.
"""

import argparse
import json
import sys
import urllib.request

NODE_INTERFACE = "0x00000000000000000000000000000000000000c8"

# ---------------------------------------------------------------------------
# keccak-256 for function selectors (hashlib.sha3_256 is not keccak)
# ---------------------------------------------------------------------------

_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
_ROT = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]
_MASK = (1 << 64) - 1


def _rol(x, n):
    n %= 64
    if n == 0:
        return x
    return ((x << n) | (x >> (64 - n))) & _MASK


def _keccak_f(s):
    for rc in _RC:
        c = [s[x][0] ^ s[x][1] ^ s[x][2] ^ s[x][3] ^ s[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        s = [[s[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(s[x][y], _ROT[x][y])
        s = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)]
             for x in range(5)]
        s[0][0] ^= rc
    return s


def keccak256(data):
    rate = 136
    buf = bytearray(data) + b"\x01"
    buf += b"\x00" * ((-len(buf)) % rate)
    buf[-1] |= 0x80
    s = [[0] * 5 for _ in range(5)]
    for off in range(0, len(buf), rate):
        block = buf[off:off + rate]
        for i in range(rate // 8):
            s[i % 5][i // 5] ^= int.from_bytes(block[8 * i:8 * i + 8], "little")
        s = _keccak_f(s)
    out = b""
    for i in range(4):
        out += s[i % 5][i // 5].to_bytes(8, "little")
    return out


def selector(signature):
    return "0x" + keccak256(signature.encode()).hex()[:8]


# ---------------------------------------------------------------------------
# JSON-RPC
# ---------------------------------------------------------------------------

class RpcError(RuntimeError):
    def __init__(self, method, error):
        super().__init__("%s: %s" % (method, error))
        self.method = method
        self.error = error

    def is_revert(self):
        msg = str(self.error.get("message", "")) if isinstance(self.error, dict) else str(self.error)
        return "revert" in msg.lower()


def rpc_call(url, method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "arb-batch-status/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        reply = json.loads(resp.read().decode())
    if "error" in reply:
        raise RpcError(method, reply["error"])
    return reply["result"]


def eth_call(url, to, data, rpc=rpc_call):
    return rpc(url, "eth_call", [{"to": to, "data": data}, "latest"])


# ---------------------------------------------------------------------------
# NodeInterface calls
# ---------------------------------------------------------------------------

def encode_find_batch(block_number):
    """findBatchContainingBlock(uint64 blockNum)"""
    return selector("findBatchContainingBlock(uint64)") + "%064x" % block_number


def encode_l1_confirmations(block_hash):
    """getL1Confirmations(bytes32 blockHash)"""
    h = block_hash[2:] if block_hash.startswith("0x") else block_hash
    if len(h) != 64:
        raise ValueError("block hash must be 32 bytes")
    return selector("getL1Confirmations(bytes32)") + h


def decode_uint(result):
    h = result[2:] if result.startswith("0x") else result
    return int(h[:64], 16) if h else 0


def find_batch(url, block_number, rpc=rpc_call):
    """Return the batch number holding `block_number`, or None if it is not in any batch yet."""
    try:
        return decode_uint(eth_call(url, NODE_INTERFACE, encode_find_batch(block_number), rpc))
    except RpcError as e:
        if e.is_revert():
            return None
        raise


def l1_confirmations(url, block_hash, rpc=rpc_call):
    return decode_uint(eth_call(url, NODE_INTERFACE, encode_l1_confirmations(block_hash), rpc))


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def classify(block_number, batch, safe_number, finalized_number):
    if batch is None:
        return "NOT_POSTED"
    if block_number <= finalized_number:
        return "FINALIZED"
    if block_number <= safe_number:
        return "SAFE"
    return "POSTED"


STATUS_HELP = {
    "NOT_POSTED": "only in the sequencer feed, no batch on L1 yet",
    "POSTED": "batch is on L1 but the node does not report it as safe yet",
    "SAFE": "batch is in an L1 block, at or below the safe head",
    "FINALIZED": "batch is in a finalized L1 block, at or below the finalized head",
}


def block_status(url, block_number=None, tx_hash=None, rpc=rpc_call):
    if (block_number is None) == (tx_hash is None):
        raise ValueError("give exactly one of block_number or tx_hash")
    tx_index = None
    if tx_hash is not None:
        receipt = rpc(url, "eth_getTransactionReceipt", [tx_hash])
        if receipt is None:
            raise RuntimeError("transaction %s not found" % tx_hash)
        block_number = int(receipt["blockNumber"], 16)
        tx_index = int(receipt["transactionIndex"], 16)

    block = rpc(url, "eth_getBlockByNumber", [hex(block_number), False])
    if block is None:
        raise RuntimeError("block %d not found" % block_number)
    latest = rpc(url, "eth_getBlockByNumber", ["latest", False])
    safe = rpc(url, "eth_getBlockByNumber", ["safe", False])
    finalized = rpc(url, "eth_getBlockByNumber", ["finalized", False])

    batch = find_batch(url, block_number, rpc)
    confs = l1_confirmations(url, block["hash"], rpc)
    safe_n = int(safe["number"], 16)
    fin_n = int(finalized["number"], 16)
    status = classify(block_number, batch, safe_n, fin_n)

    out = {
        "block_number": block_number,
        "block_hash": block["hash"],
        "timestamp": int(block["timestamp"], 16),
        "l1_origin_block": int(block["l1BlockNumber"], 16) if "l1BlockNumber" in block else None,
        "batch": batch,
        "l1_confirmations": confs,
        "latest_head": int(latest["number"], 16),
        "safe_head": safe_n,
        "finalized_head": fin_n,
        "status": status,
    }
    if tx_hash is not None:
        out["tx_hash"] = tx_hash
        out["tx_index"] = tx_index
    return out


def _distance(block_number, head):
    d = head - block_number
    if d >= 0:
        return "block is %d below" % d
    return "block is %d above" % (-d)


def format_report(r):
    lines = []
    if "tx_hash" in r:
        lines.append("tx:                %s (index %d)" % (r["tx_hash"], r["tx_index"]))
    lines += [
        "L2 block:          %d" % r["block_number"],
        "block hash:        %s" % r["block_hash"],
        "L2 timestamp:      %d" % r["timestamp"],
        "L1 origin block:   %s" % (r["l1_origin_block"] if r["l1_origin_block"] is not None else "n/a"),
        "batch:             %s" % (r["batch"] if r["batch"] is not None else "none yet"),
        "L1 confirmations:  %d" % r["l1_confirmations"],
        "latest head:       %d (%s)" % (r["latest_head"], _distance(r["block_number"], r["latest_head"])),
        "safe head:         %d (%s)" % (r["safe_head"], _distance(r["block_number"], r["safe_head"])),
        "finalized head:    %d (%s)" % (r["finalized_head"], _distance(r["block_number"], r["finalized_head"])),
        "status:            %s (%s)" % (r["status"], STATUS_HELP[r["status"]]),
    ]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description="Show the batch and L1 confirmation status of an Arbitrum block or transaction.")
    p.add_argument("--rpc", required=True, help="Arbitrum JSON-RPC URL")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--block", type=int, help="L2 block number")
    g.add_argument("--tx", help="L2 transaction hash")
    p.add_argument("--json", action="store_true", help="print JSON")
    a = p.parse_args(argv)

    res = block_status(a.rpc, block_number=a.block, tx_hash=a.tx)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(format_report(res))
    return 0 if res["status"] != "NOT_POSTED" else 2


if __name__ == "__main__":
    sys.exit(main())
