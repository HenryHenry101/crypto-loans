"""Production-ready HTTP backend orchestrator for Crypto Loans."""
from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Deque, Dict, Optional, Tuple

from store import LoanStore

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
LOGGER = logging.getLogger("crypto-loans.backend")


class APIError(Exception):
    def __init__(self, status: int, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details or {}


class RateLimiter:
    """IP-based rate limiter to mitigate abusive clients."""

    def __init__(self, limit: int = 120, window: int = 60) -> None:
        self.limit = limit
        self.window = window
        self._records: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            bucket = self._records.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


class MoneriumClient:
    """Thin Monerium API helper handling OAuth2 client credentials."""

    def __init__(self) -> None:
        self.base_url = os.getenv("MONERIUM_BASE_URL", "https://api.monerium.dev")
        self.client_id = os.getenv("MONERIUM_CLIENT_ID")
        self.client_secret = os.getenv("MONERIUM_CLIENT_SECRET")
        self.scope = os.getenv(
            "MONERIUM_SCOPE",
            "offline_access transactions:write transactions:read",
        )
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
    """Wrapper around Avalanche Bridge API endpoints."""

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


class PriceOracleClient:
    """Fetches BTC/EUR reference prices with caching and fallback."""

    def __init__(self) -> None:
        self.endpoint = os.getenv(
            "PRICE_FEED_URL",
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=eur",
        )
        self.static_price = os.getenv("STATIC_BTC_EUR")
        self.timeout = int(os.getenv("PRICE_FEED_TIMEOUT", "10"))
        self.cache_ttl = int(os.getenv("PRICE_FEED_CACHE", "60"))
        self._cache: Optional[Tuple[float, float]] = None  # (timestamp, price)

    def current_price(self) -> float:
        if self.static_price is not None:
            return float(self.static_price)
        now = time.time()
        if self._cache and now - self._cache[0] < self.cache_ttl:
            return self._cache[1]
        try:
            with urllib.request.urlopen(self.endpoint, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                price = float(payload["bitcoin"]["eur"])
                self._cache = (now, price)
                return price
        except Exception as exc:  # pragma: no cover - network error path
            if self._cache:
                LOGGER.warning("Price feed failed (%s), returning cached price", exc)
                return self._cache[1]
            raise APIError(HTTPStatus.BAD_GATEWAY, "Unable to fetch BTC/EUR price", {"error": str(exc)})


class RiskMonitor(threading.Thread):
    """Background task that recalculates LTV and flags risky loans."""

    def __init__(self, store: LoanStore, oracle: PriceOracleClient, *, warn_ltv: float = 0.65, liquidate_ltv: float = 0.7,
                 interval: int = 60) -> None:
        super().__init__(daemon=True)
        self.store = store
        self.oracle = oracle
        self.warn_ltv = warn_ltv
        self.liquidate_ltv = liquidate_ltv
        self.interval = interval
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:  # pragma: no cover - background loop
        LOGGER.info("Risk monitor started")
        while not self._stop_event.is_set():
            try:
                price = self.oracle.current_price()
                loans = self.store.list()
                for loan_id, loan in loans.items():
                    if not loan or loan.get("status") != "active":
                        continue
                    collateral = float(loan.get("collateralBTCb") or 0)
                    principal = float(loan.get("principal") or 0)
                    if collateral <= 0:
                        continue
                    collateral_value = collateral * price
                    if collateral_value <= 0:
                        continue
                    ltv = principal / collateral_value
                    self.store.update_health(loan_id, price_eur=price, ltv=ltv)
                    if ltv >= self.liquidate_ltv:
                        LOGGER.warning("Loan %s marked default due to LTV %.3f", loan_id, ltv)
                        self.store.mark_default(loan_id, "ltv-threshold", ltv)
                    elif ltv >= self.warn_ltv:
                        self.store.record_event(
                            loan_id,
                            "ltv-warning",
                            {"ltv": ltv, "threshold": self.warn_ltv},
                        )
            except APIError as exc:
                LOGGER.error("Risk monitor error: %s", exc)
            except Exception as exc:  # pragma: no cover - unforeseen error path
                LOGGER.exception("Unexpected risk monitor failure: %s", exc)
            self._stop_event.wait(self.interval)
        LOGGER.info("Risk monitor stopped")


STORE = LoanStore()
MONERIUM = MoneriumClient()
BRIDGE = AvalancheBridgeClient()
PRICES = PriceOracleClient()
RATE_LIMITER = RateLimiter(
    limit=int(os.getenv("RATE_LIMIT", "120")),
    window=int(os.getenv("RATE_LIMIT_WINDOW", "60")),
)
RISK_MONITOR = RiskMonitor(STORE, PRICES, interval=int(os.getenv("RISK_INTERVAL", "120")))


class Handler(BaseHTTPRequestHandler):
    server_version = "CryptoLoans/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # pragma: no cover - logging override
        LOGGER.info("%s - %s", self.address_string(), format % args)

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

    def _rate_limit(self) -> bool:
        remote = self.client_address[0]
        if not RATE_LIMITER.allow(remote):
            self._json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "rate-limit", "retryIn": RATE_LIMITER.window})
            return False
        return True

    def do_OPTIONS(self) -> None:  # noqa: N802 - preflight support
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,X-API-Key")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,OPTIONS")
        self.end_headers()

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self._json(HTTPStatus.OK, {"ok": True, "version": self.server_version})
            return
        if not self._rate_limit() or not self._ensure_authorized():
            return
        if parsed.path == "/loans":
            self._json(HTTPStatus.OK, {"data": list(STORE.list().values())})
            return
        if parsed.path.startswith("/loans/"):
            parts = parsed.path.split("/")
            loan_id = parts[2]
            if len(parts) == 4 and parts[3] == "history":
                history = STORE.history(loan_id)
                self._json(HTTPStatus.OK, {"data": history})
                return
            loan = STORE.get(loan_id)
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
        if parsed.path == "/pricing/btc-eur":
            try:
                price = PRICES.current_price()
            except APIError as exc:
                self._json(exc.status, {"error": exc.message, "details": exc.details})
                return
            self._json(HTTPStatus.OK, {"data": {"price": price}})
            return
        if parsed.path == "/metrics":
            loans = STORE.list()
            active = sum(1 for loan in loans.values() if loan and loan.get("status") == "active")
            repaid = sum(1 for loan in loans.values() if loan and loan.get("status") == "repaid")
            defaulted = sum(1 for loan in loans.values() if loan and loan.get("status") == "defaulted")
            self._json(
                HTTPStatus.OK,
                {"data": {"total": len(loans), "active": active, "repaid": repaid, "defaulted": defaulted}},
            )
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in {"/health"} and (not self._rate_limit() or not self._ensure_authorized()):
            return
        payload = self._read_json()
        try:
            if parsed.path == "/loans":
                loan = self._handle_create_loan(payload)
                self._json(HTTPStatus.CREATED, {"data": loan})
                return
            if parsed.path == "/repay":
                loan_id = str(payload.get("loanId"))
                amount = float(payload.get("amount", 0))
                via = payload.get("via", "manual")
                loan = STORE.mark_repaid(loan_id, amount)
                STORE.record_event(loan_id, "repayment-submitted", {"amount": amount, "via": via})
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
                STORE.record_event(payload.get("loanId", "unknown"), "bridge-wrap", result)
                self._json(HTTPStatus.OK, {"data": result})
                return
            if parsed.path == "/bridge/unwrap":
                result = BRIDGE.initiate_unwrap(
                    float(payload.get("amount", 0)),
                    payload["btcAddress"],
                    payload["sourceAddress"],
                    payload.get("network", "mainnet"),
                )
                STORE.record_event(payload.get("loanId", "unknown"), "bridge-unwrap", result)
                self._json(HTTPStatus.OK, {"data": result})
                return
            if parsed.path == "/loans/default":
                loan_id = payload["loanId"]
                reason = payload.get("reason", "manual-default")
                record = STORE.mark_default(loan_id, reason)
                self._json(HTTPStatus.OK, {"data": record})
                return
        except KeyError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": f"missing field {exc.args[0]}"})
            return
        except APIError as exc:
            self._json(exc.status, {"error": exc.message, "details": exc.details})
            return
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if not self._rate_limit() or not self._ensure_authorized():
            return
        if not parsed.path.startswith("/loans/"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        loan_id = parsed.path.split("/")[2]
        payload = self._read_json()
        status = payload.get("status")
        if status not in {"active", "repaid", "defaulted"}:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid status"})
            return
        record = STORE.update(loan_id, status=status)
        STORE.record_event(loan_id, "status-updated", {"status": status})
        self._json(HTTPStatus.OK, {"data": record})

    def _handle_create_loan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        principal = float(payload.get("principal", 0))
        collateral = float(payload.get("collateralBTCb", 0))
        ltv = float(payload.get("ltv", 0))
        if not principal or not collateral:
            raise ValueError("principal and collateralBTCb are required")
        if ltv <= 0 or ltv > 70:
            raise ValueError("ltv must be between 0 and 70")
        duration = int(payload.get("duration", 0))
        if duration <= 0:
            raise ValueError("duration must be greater than zero")
        loan = STORE.create(payload)
        STORE.record_event(loan["loanId"], "loan-validated", {"principal": principal, "collateral": collateral})
        if payload.get("disburseVia") == "monerium" and payload.get("iban"):
            payout = MONERIUM.redeem(payload["iban"], principal, payload.get("reference", "Loan disbursement"))
            loan = STORE.update(loan["loanId"], moneriumPayout=payout)
            STORE.record_event(loan["loanId"], "payout-executed", {"provider": "monerium"})
        return loan


def run(port: int = 8080) -> None:
    if not RISK_MONITOR.is_alive():
        RISK_MONITOR.start()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    LOGGER.info("Crypto Loans backend listening on http://0.0.0.0:%s", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - manual stop
        LOGGER.info("Shutting down due to interrupt")
    finally:
        RISK_MONITOR.stop()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    run()
