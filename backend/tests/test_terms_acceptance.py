import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from http import HTTPStatus
from unittest import mock

hexbytes_stub = types.ModuleType("hexbytes")
hexbytes_stub.HexBytes = lambda value: value
sys.modules.setdefault("hexbytes", hexbytes_stub)

from backend.store import LoanStore

sys.modules.setdefault("store", __import__("backend.store", fromlist=["*"]))

from backend import server


@unittest.skipUnless(server.Account and server.encode_structured_data, "eth-account dependency required")
class TermsAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="terms-acceptance-")
        self.db_path = os.path.join(self.tmpdir, "store.db")
        self.store = LoanStore(self.db_path)
        self._original_store = server.STORE
        self._original_avalanche = server.AVALANCHE_COORDINATOR
        self._original_ethereum = server.ETHEREUM_COORDINATOR
        server.STORE = self.store
        server.AVALANCHE_COORDINATOR = mock.Mock()
        server.AVALANCHE_COORDINATOR.available.return_value = False
        server.ETHEREUM_COORDINATOR = mock.Mock()
        server.ETHEREUM_COORDINATOR.available.return_value = False

    def tearDown(self) -> None:
        server.STORE = self._original_store
        server.AVALANCHE_COORDINATOR = self._original_avalanche
        server.ETHEREUM_COORDINATOR = self._original_ethereum
        self.store.close()
        shutil.rmtree(self.tmpdir)

    def _build_signature(self, wallet: str, timestamp: int) -> str:
        domain = dict(server.TERMS_DOMAIN)
        domain["chainId"] = int(domain.get("chainId") or server.TERMS_CHAIN_ID)
        domain["verifyingContract"] = server._checksum_address(domain.get("verifyingContract", server.TERMS_VERIFIER))
        message = {
            "wallet": server._checksum_address(wallet),
            "termsHash": server.TERMS_HASH.lower(),
            "timestamp": timestamp,
        }
        typed_data = {
            "types": server.TERMS_TYPES,
            "primaryType": "TermsAcceptance",
            "domain": domain,
            "message": message,
        }
        signable = server.encode_structured_data(typed_data)
        signature_bytes = server.Account.sign_message(signable, private_key=self._private_key).signature
        return signature_bytes.hex()

    def _build_payload(self, wallet: str, signature: str, timestamp: int) -> dict:
        return {
            "borrower": wallet,
            "principal": 1000.0,
            "collateralBTCb": 0.5,
            "duration": 30 * 86400,
            "ltv": 50,
            "termsAcceptance": {
                "wallet": wallet,
                "termsHash": server.TERMS_HASH,
                "timestamp": timestamp,
                "signature": signature,
                "termsVersion": server.TERMS_VERSION,
            },
        }

    def test_create_loan_requires_terms_acceptance(self) -> None:
        handler = server.Handler.__new__(server.Handler)
        payload = {
            "borrower": "0x1234567890abcdef1234567890abcdef12345678",
            "principal": 1000,
            "collateralBTCb": 0.4,
            "duration": 15 * 86400,
            "ltv": 40,
        }
        with self.assertRaises(server.APIError) as ctx:
            handler._handle_create_loan(payload)
        self.assertEqual(ctx.exception.status, HTTPStatus.PRECONDITION_REQUIRED)

    def test_create_loan_persists_terms_acceptance(self) -> None:
        handler = server.Handler.__new__(server.Handler)
        account = server.Account.create()
        self._private_key = account.key
        timestamp = int(time.time())
        signature = self._build_signature(account.address, timestamp)
        payload = self._build_payload(account.address, signature, timestamp)
        loan = handler._handle_create_loan(payload)
        self.assertEqual(loan["termsAcceptedHash"], server.TERMS_HASH.lower())
        self.assertEqual(loan["termsAcceptedAt"], timestamp)
        self.assertEqual(loan["termsAcceptance"]["wallet"], account.address.lower())
        self.assertEqual(loan["termsAcceptance"]["termsVersion"], server.TERMS_VERSION)
        self.assertEqual(loan["termsSignature"], signature)
        stored_acceptance = self.store.get_terms_acceptance(account.address)
        self.assertIsNotNone(stored_acceptance)
        assert stored_acceptance is not None
        self.assertEqual(stored_acceptance["wallet"], account.address.lower())
        self.assertEqual(stored_acceptance["termsHash"], server.TERMS_HASH.lower())
        self.assertEqual(stored_acceptance["acceptedAt"], timestamp)
        history = self.store.history(loan["loanId"])
        events = [event["event"] for event in history]
        self.assertIn("terms-accepted", events)


if __name__ == "__main__":
    unittest.main()
