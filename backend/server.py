
"""Minimal backend stub exposing core endpoints for the crypto loans platform.

This module avoids third-party dependencies so it can run in constrained environments.
It provides illustrative handlers that orchestrate loans, Monerium payouts and
cross-chain messages. Replace with a production-ready framework (FastAPI, NestJS)
when deploying for real users.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict


class LoanStore:
    """In-memory store with basic synchronization."""

    def __init__(self) -> None:
        self._loans: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        loan_id = payload["loanId"]
        with self._lock:
            self._loans[loan_id] = payload
        return payload

    def list(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._loans)

    def mark_repaid(self, loan_id: str, amount: float) -> Dict[str, Any]:
        with self._lock:
            loan = self._loans.setdefault(loan_id, {})
            loan["status"] = "repaid"
            loan["repaidAmount"] = amount
            loan["repaidAt"] = int(time.time())
            return loan


LOANS = LoanStore()


class Handler(BaseHTTPRequestHandler):
    server_version = "CryptoLoans/0.1"

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"ok": True})
            return
        if self.path == "/loans":
            self._json(200, {"data": list(LOANS.list().values())})
            return
        self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length) if length else b"{}"
        payload = json.loads(data or b"{}")
        if self.path == "/loans":
            created = LOANS.create(payload)
            self._json(201, {"data": created})
            return
        if self.path == "/repay":
            loan_id = payload.get("loanId")
            amount = float(payload.get("amount", 0))
            updated = LOANS.mark_repaid(loan_id, amount)
            self._json(200, {"data": updated})
            return
        self._json(404, {"error": "Not found"})


def run(port: int = 8080) -> None:
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Crypto Loans backend listening on http://0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
