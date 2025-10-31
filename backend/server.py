"""Enhanced backend stub orchestrating Monerium, bridge operations and secured loan storage."""

from __future__ import annotations

import base64
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional, Tuple


class LoanStore:
    """Thread-safe in-memory store with audit trail support."""

    def __init__(self) -> None:
        self._loans: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"loan-{self._counter:06d}"

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            loan_id = str(payload.get("loanId") or self._next_id())
            payload = dict(payload)
            payload["loanId"] = loan_id
            payload.setdefault("status", "active")
            payload.setdefault("createdAt", int(time.time()))
            payload.setdefault("history", [])
            self._loans[loan_id] = payload
            return dict(payload)

    def list(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {loan_id: dict(data) for loan_id, data in self._loans.items()}

    def get(self, loan_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._loans.get(loan_id)
            return dict(record) if record else None

    def update(self, loan_id: str, **fields: Any) -> Dict[str, Any]:
        with self._lock:
            loan = self._loans.setdefault(loan_id, {"loanId": loan_id, "history": []})
            loan.update(fields)
            return dict(loan)

    def record_event(self, loan_id: str, event: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            loan = self._loans.setdefault(loan_id, {"loanId": loan_id, "history": []})
            entry = {
                "event": event,
                "metadata": metadata or {},
                "timestamp": int(time.time()),
            }
            loan.setdefault("history", []).append(entry)
            return dict(entry)

    def mark_repaid(self, loan_id: str, amount: float) -> Dict[str, Any]:
        event = self.record_event(loan_id, "repayment-recorded", {"amount": amount})
        with self._lock:
            loan = self._loans.setdefault(loan_id, {"loanId": loan_id, "history": [event]})
            loan["status"] = "repaid"
            loan["repaidAmount"] = amount
            loan["repaidAt"] = event["timestamp"]
            return dict(loan)


class APIError(Exception):
    def __init__(self, status: int, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details or {}


class MoneriumClient:
    """Tiny Monerium API helper handling OAuth2 client credentials."""

    def __init__(self) -> None:
        self.base_url = os.getenv("MONERIUM_BASE_URL", "https://api.monerium.dev")
        self.client_id = os.getenv("MONERIUM_CLIENT_ID")
        self.client_secret = os.getenv("MONERIUM_CLIENT_SECRET")
        self.scope = os.getenv("MONERIUM_SCOPE", "offline_access transactions:write transactions:read")
        self._token: Optional[Tuple[str, float]] = None
        self._lock = threading.Lock()

    def _auth_header(self) -> str:
        if not self.client_id or not self.client_secret:
            raise APIError(HTTPStatus.PRECONDITION_REQUIRED, "Missing Monerium credentials")
        token = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        return "Basic " + base64.b64encode(token).decode("ascii")

    def _obtain_token(self) -> str:
        with self._lock:
            if self._token and self._token[1] - time.time() > 60:
                return self._token[0]

            data = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": self.scope}).encode("utf-8")
            request = urllib.request.Request(
                f"{self.base_url}/oauth/token",
                data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": self._auth_header(),
                },
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            access_token = payload["access_token"]
            expires_in = int(payload.get("expires_in", 3600))
            self._token = (access_token, time.time() + expires_in)
            return access_token

    def _authorized_request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        token = self._obtain_token()
        data = json.dumps(body or {}).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # pragma: no cover - network error path
            details = exc.read().decode("utf-8") if exc.fp else exc.reason
            raise APIError(exc.code, "Monerium request failed", {"response": details})
        return json.loads(raw) if raw else {}

    def redeem(self, iban: str, amount_eur: float, reference: str) -> Dict[str, Any]:
        body = {
            "amount": {"currency": "EUR", "value": str(amount_eur)},
            "counterpart": {"iban": iban},
            "reference": reference,
        }
        return self._authorized_request("POST", "/money-out/transactions", body)

    def issue_eure(self, ethereum_address: str, amount_eur: float) -> Dict[str, Any]:
        body = {
            "amount": {"currency": "EUR", "value": str(amount_eur)},
            "address": ethereum_address,
        }
        return self._authorized_request("POST", "/wallets/transactions", body)


class AvalancheBridgeClient:
    """Wrapper around the public Avalanche Bridge API endpoints."""

    def __init__(self) -> None:
        self.base_url = os.getenv("AVALANCHE_BRIDGE_URL", "https://bridge-api.avax.network")
        self.timeout = int(os.getenv("AVALANCHE_BRIDGE_TIMEOUT", "15"))

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # pragma: no cover - network error path
            details = exc.read().decode("utf-8") if exc.fp else exc.reason
            raise APIError(exc.code, "Avalanche bridge request failed", {"response": details})
        return json.loads(raw) if raw else {}

    def initiate_wrap(self, btc_tx_id: str, target_address: str, network: str = "mainnet") -> Dict[str, Any]:
        return self._request(
            "POST",
            "/v1/wrap",
            {
                "btcTx": btc_tx_id,
                "network": network,
                "targetAddress": target_address,
            },
        )

    def initiate_unwrap(self, amount: float, btc_address: str, source_address: str, network: str = "mainnet") -> Dict[str, Any]:
        return self._request(
            "POST",
            "/v1/unwrap",
            {
                "amount": amount,
                "btcAddress": btc_address,
                "sourceAddress": source_address,
                "network": network,
            },
        )

    def status(self, transaction_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/transactions/{transaction_id}")


LOANS = LoanStore()
MONERIUM = MoneriumClient()
BRIDGE = AvalancheBridgeClient()


class Handler(BaseHTTPRequestHandler):
    server_version = "CryptoLoans/0.2"

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def _ensure_authorized(self) -> bool:
        api_key = os.getenv("API_KEY")
        if not api_key:
            return True
        provided = self.headers.get("X-API-Key", "")
        if not provided or not hmac.compare_digest(api_key, provided):
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self._json(HTTPStatus.OK, {"ok": True})
            return
        if not self._ensure_authorized():
            return
        if parsed.path == "/loans":
            self._json(HTTPStatus.OK, {"data": list(LOANS.list().values())})
            return
        if parsed.path.startswith("/loans/"):
            loan_id = parsed.path.split("/")[-1]
            loan = LOANS.get(loan_id)
            if not loan:
                self._json(HTTPStatus.NOT_FOUND, {"error": "loan not found"})
                return
            self._json(HTTPStatus.OK, {"data": loan})
            return
        if parsed.path == "/bridge/status":
            query = urllib.parse.parse_qs(parsed.query)
            tx_id = query.get("id", [""])[0]
            if not tx_id:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "missing id"})
                return
            try:
                data = BRIDGE.status(tx_id)
            except APIError as exc:
                self._json(exc.status, {"error": exc.message, "details": exc.details})
                return
            self._json(HTTPStatus.OK, {"data": data})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in {"/health"} and not self._ensure_authorized():
            return
        payload = self._read_json()
        try:
            if parsed.path == "/loans":
                loan = LOANS.create(payload)
                LOANS.record_event(loan["loanId"], "loan-created", {k: loan.get(k) for k in ("principal", "ltv", "duration")})
                if payload.get("disburseVia") == "monerium" and payload.get("iban"):
                    payout = MONERIUM.redeem(payload["iban"], float(payload.get("principal", 0)), payload.get("reference", "Loan disbursement"))
                    loan = LOANS.update(loan["loanId"], moneriumPayout=payout)
                self._json(HTTPStatus.CREATED, {"data": loan})
                return
            if parsed.path == "/repay":
                loan_id = str(payload.get("loanId"))
                amount = float(payload.get("amount", 0))
                loan = LOANS.mark_repaid(loan_id, amount)
                LOANS.record_event(loan_id, "repayment-submitted", {"amount": amount, "via": payload.get("via", "manual")})
                self._json(HTTPStatus.OK, {"data": loan})
                return
            if parsed.path == "/monerium/redeem":
                result = MONERIUM.redeem(payload["iban"], float(payload.get("amount", 0)), payload.get("reference", "Loan payout"))
                self._json(HTTPStatus.OK, {"data": result})
                return
            if parsed.path == "/monerium/issue":
                result = MONERIUM.issue_eure(payload["address"], float(payload.get("amount", 0)))
                self._json(HTTPStatus.OK, {"data": result})
                return
            if parsed.path == "/bridge/wrap":
                result = BRIDGE.initiate_wrap(payload["btcTxId"], payload["targetAddress"], payload.get("network", "mainnet"))
                LOANS.record_event(payload.get("loanId", "unknown"), "bridge-wrap", result)
                self._json(HTTPStatus.OK, {"data": result})
                return
            if parsed.path == "/bridge/unwrap":
                result = BRIDGE.initiate_unwrap(
                    float(payload.get("amount", 0)),
                    payload["btcAddress"],
                    payload["sourceAddress"],
                    payload.get("network", "mainnet"),
                )
                LOANS.record_event(payload.get("loanId", "unknown"), "bridge-unwrap", result)
                self._json(HTTPStatus.OK, {"data": result})
                return
        except KeyError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": f"missing field {exc.args[0]}"})
            return
        except APIError as exc:
            self._json(exc.status, {"error": exc.message, "details": exc.details})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})


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
