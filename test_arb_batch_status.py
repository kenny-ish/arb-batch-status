import unittest

import arb_batch_status as m

# Real values from Arbitrum One, captured 2026-10-10.
RPC = "http://arb"
BLOCK_NUMBER = 513466368  # 0x1e9ae000
BLOCK = {
    "number": "0x1e9ae000",
    "hash": "0xfa7f4037b7033e4da3121ca512f7a4b9e95d23924445d187a3364542bd2ede3d",
    "timestamp": "0x6ac9fda4",
    "l1BlockNumber": "0x18f2f4e",  # 26160974
    "sendRoot": "0x67f7584a93f87acdaa23da92247905fd830159afbce56732b3b5b7793cc24975",
}
TX_HASH = "0x4f6a49e57da3042ec40605815f4817084bcec43d486b62ab865b368b339d3489"
RECEIPT = {"blockNumber": "0x1e9ae000", "blockHash": BLOCK["hash"], "transactionIndex": "0x1", "status": "0x1"}
LATEST = {"number": "0x1e9aeb7f", "hash": "0xea61b46395203ed9ddfb18a32803cf5525e33c618f8360632217f8b81a06cad7",
          "timestamp": "0x6ac9ffc8", "l1BlockNumber": "0x18f2fa3"}
SAFE = {"number": "0x1e9ae352", "hash": "0x" + "aa" * 32, "timestamp": "0x6ac9fe10"}        # 513467218
FINALIZED = {"number": "0x1e9addb9", "hash": "0x" + "bb" * 32, "timestamp": "0x6ac9fcf0"}   # 513465785

FIND_BATCH_CALLDATA = "0x81f1adaf000000000000000000000000000000000000000000000000000000001e9ae000"
FIND_BATCH_RESULT = "0x000000000000000000000000000000000000000000000000000000000014a850"  # 1353808
CONF_CALLDATA = "0xe5ca238cfa7f4037b7033e4da3121ca512f7a4b9e95d23924445d187a3364542bd2ede3d"
CONF_RESULT = "0x000000000000000000000000000000000000000000000000000000000000003b"  # 59
LATEST_FIND_BATCH_CALLDATA = "0x81f1adaf000000000000000000000000000000000000000000000000000000001e9aeb7f"
LATEST_CONF_CALLDATA = "0xe5ca238cea61b46395203ed9ddfb18a32803cf5525e33c618f8360632217f8b81a06cad7"
ZERO = "0x" + "00" * 32

REVERT = {"code": -32000, "message": "execution reverted"}


def fake_rpc(url, method, params):
    assert url == RPC
    if method == "eth_getTransactionReceipt":
        return RECEIPT if params[0] == TX_HASH else None
    if method == "eth_getBlockByNumber":
        tag = params[0]
        return {
            "latest": LATEST, LATEST["number"]: LATEST,
            "safe": SAFE, "finalized": FINALIZED,
            BLOCK["number"]: BLOCK,
        }.get(tag)
    if method == "eth_call":
        assert params[0]["to"] == m.NODE_INTERFACE
        data = params[0]["data"]
        if data == FIND_BATCH_CALLDATA:
            return FIND_BATCH_RESULT
        if data == CONF_CALLDATA:
            return CONF_RESULT
        if data == LATEST_FIND_BATCH_CALLDATA:
            raise m.RpcError("eth_call", REVERT)
        if data == LATEST_CONF_CALLDATA:
            return ZERO
    raise AssertionError("unexpected %s %s" % (method, params))


class SelectorTest(unittest.TestCase):
    def test_keccak_empty(self):
        self.assertEqual(m.keccak256(b"").hex(),
                         "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")

    def test_node_interface_selectors(self):
        self.assertEqual(m.selector("findBatchContainingBlock(uint64)"), "0x81f1adaf")
        self.assertEqual(m.selector("getL1Confirmations(bytes32)"), "0xe5ca238c")
        self.assertEqual(m.selector("transfer(address,uint256)"), "0xa9059cbb")


class EncodingTest(unittest.TestCase):
    def test_encode_find_batch(self):
        self.assertEqual(m.encode_find_batch(BLOCK_NUMBER), FIND_BATCH_CALLDATA)

    def test_encode_l1_confirmations(self):
        self.assertEqual(m.encode_l1_confirmations(BLOCK["hash"]), CONF_CALLDATA)
        with self.assertRaises(ValueError):
            m.encode_l1_confirmations("0x1234")

    def test_decode_uint(self):
        self.assertEqual(m.decode_uint(FIND_BATCH_RESULT), 1353808)
        self.assertEqual(m.decode_uint(CONF_RESULT), 59)
        self.assertEqual(m.decode_uint("0x"), 0)


class NodeInterfaceTest(unittest.TestCase):
    def test_find_batch(self):
        self.assertEqual(m.find_batch(RPC, BLOCK_NUMBER, rpc=fake_rpc), 1353808)

    def test_find_batch_not_posted(self):
        self.assertIsNone(m.find_batch(RPC, int(LATEST["number"], 16), rpc=fake_rpc))

    def test_find_batch_other_errors_propagate(self):
        def broken(url, method, params):
            raise m.RpcError("eth_call", {"code": -32000, "message": "node is syncing"})
        with self.assertRaises(m.RpcError):
            m.find_batch(RPC, BLOCK_NUMBER, rpc=broken)

    def test_l1_confirmations(self):
        self.assertEqual(m.l1_confirmations(RPC, BLOCK["hash"], rpc=fake_rpc), 59)


class ClassifyTest(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(m.classify(100, None, 200, 150), "NOT_POSTED")
        self.assertEqual(m.classify(100, 5, 200, 150), "FINALIZED")
        self.assertEqual(m.classify(150, 5, 200, 150), "FINALIZED")
        self.assertEqual(m.classify(151, 5, 200, 150), "SAFE")
        self.assertEqual(m.classify(200, 5, 200, 150), "SAFE")
        self.assertEqual(m.classify(201, 5, 200, 150), "POSTED")


class StatusTest(unittest.TestCase):
    def test_block_status_real_block(self):
        r = m.block_status(RPC, block_number=BLOCK_NUMBER, rpc=fake_rpc)
        self.assertEqual(r["block_hash"], BLOCK["hash"])
        self.assertEqual(r["timestamp"], 1791622564)
        self.assertEqual(r["l1_origin_block"], 26160974)
        self.assertEqual(r["batch"], 1353808)
        self.assertEqual(r["l1_confirmations"], 59)
        self.assertEqual(r["safe_head"], 513467218)
        self.assertEqual(r["finalized_head"], 513465785)
        self.assertEqual(r["status"], "SAFE")
        self.assertNotIn("tx_hash", r)

    def test_block_status_by_tx(self):
        r = m.block_status(RPC, tx_hash=TX_HASH, rpc=fake_rpc)
        self.assertEqual(r["block_number"], BLOCK_NUMBER)
        self.assertEqual(r["tx_index"], 1)
        self.assertEqual(r["batch"], 1353808)
        text = m.format_report(r)
        self.assertIn("tx:                %s (index 1)" % TX_HASH, text)
        self.assertIn("batch:             1353808", text)
        self.assertIn("status:            SAFE", text)
        self.assertIn("finalized head:    513465785 (block is 583 above)", text)

    def test_block_status_latest_not_posted(self):
        r = m.block_status(RPC, block_number=int(LATEST["number"], 16), rpc=fake_rpc)
        self.assertIsNone(r["batch"])
        self.assertEqual(r["l1_confirmations"], 0)
        self.assertEqual(r["status"], "NOT_POSTED")
        self.assertIn("batch:             none yet", m.format_report(r))

    def test_unknown_tx(self):
        with self.assertRaises(RuntimeError):
            m.block_status(RPC, tx_hash="0x" + "00" * 32, rpc=fake_rpc)

    def test_requires_exactly_one_target(self):
        with self.assertRaises(ValueError):
            m.block_status(RPC, rpc=fake_rpc)
        with self.assertRaises(ValueError):
            m.block_status(RPC, block_number=1, tx_hash=TX_HASH, rpc=fake_rpc)


if __name__ == "__main__":
    unittest.main()
