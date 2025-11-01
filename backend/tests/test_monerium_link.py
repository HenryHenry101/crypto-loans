import hashlib
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

hexbytes_stub = types.ModuleType("hexbytes")
hexbytes_stub.HexBytes = lambda value: value
sys.modules.setdefault("hexbytes", hexbytes_stub)

from backend.store import LoanStore, normalize_iban

sys.modules.setdefault("store", __import__("backend.store", fromlist=["*"]))

from backend import server


class MoneriumLinkStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="monerium-link-")
        self.db_path = os.path.join(self.tmpdir, "store.db")
        self.store = LoanStore(self.db_path)
        self._original_store = server.STORE
        self._original_monerium = server.MONERIUM
        server.STORE = self.store
        server.MONERIUM = mock.Mock()

    def tearDown(self) -> None:
        server.STORE = self._original_store
        server.MONERIUM = self._original_monerium
        self.store.close()
        shutil.rmtree(self.tmpdir)

    def test_link_wallet_creates_binding_hash(self) -> None:
        iban = "ES12 3456 7890 1234 5678"
        wallet = "0xAaBbCc"
        monerium_user_id = "usr_123"
        record = self.store.link_monerium_wallet(
            wallet,
            iban,
            monerium_user_id,
            "0xsig",
            message="msg",
            metadata={"accountId": "acct-001"},
        )
        normalized_wallet = wallet.lower()
        normalized_iban = normalize_iban(iban)
        expected_hash = hashlib.sha256(
            f"{normalized_wallet}{normalized_iban}{monerium_user_id}".encode("utf-8")
        ).hexdigest()
        self.assertEqual(record["wallet"], normalized_wallet)
        self.assertEqual(record["iban"], normalized_iban)
        self.assertEqual(record["bindingHash"], expected_hash)
        fetched = self.store.get_monerium_link(wallet)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["bindingHash"], expected_hash)
        required = self.store.require_monerium_link(wallet, iban=iban)
        self.assertEqual(required["bindingHash"], expected_hash)

    def test_require_mismatch_raises(self) -> None:
        wallet = "0xabc"
        self.store.link_monerium_wallet(wallet, "ES100000000000000000", "usr_a", "sig")
        with self.assertRaises(ValueError):
            self.store.require_monerium_link(wallet, iban="DE001234")
        with self.assertRaises(ValueError):
            self.store.require_monerium_link(wallet, monerium_user_id="usr_b")

    def test_handle_monerium_link_validates_with_monerium(self) -> None:
        payload = {
            "iban": "ES120001000200030004",
            "moneriumUserId": "usr_987",
            "signature": "0xsignature",
            "message": "message",
            "wallet": "0xCDEF",
        }
        server.MONERIUM.verify_user_iban.return_value = {"iban": payload["iban"], "id": "acct"}
        with mock.patch("backend.server._recover_wallet_from_signature", return_value="0xcdef"):
            record = server._handle_monerium_link(payload)
        server.MONERIUM.verify_user_iban.assert_called_once_with(payload["moneriumUserId"], payload["iban"])
        self.assertEqual(record["wallet"], "0xcdef")
        self.assertEqual(record["moneriumUserId"], payload["moneriumUserId"])
        normalized_iban = normalize_iban(payload["iban"])
        self.assertEqual(record["iban"], normalized_iban)
        expected_hash = hashlib.sha256(
            f"0xcdef{normalized_iban}{payload['moneriumUserId']}".encode("utf-8")
        ).hexdigest()
        self.assertEqual(record["bindingHash"], expected_hash)


if __name__ == "__main__":
    unittest.main()
