"""Production-ready HTTP backend orchestrator for Crypto Loans."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, Optional, Tuple

from hexbytes import HexBytes

try:  # pragma: no cover - optional dependency when running unit tests
    from web3 import Web3
    from web3.contract import Contract
    from web3.middleware import geth_poa_middleware
except Exception:  # pragma: no cover - fallback when web3 is unavailable
    Web3 = None  # type: ignore
    Contract = None  # type: ignore
    geth_poa_middleware = None  # type: ignore

from store import LoanStore, normalize_iban

try:  # pragma: no cover - optional dependency for signature recovery
    from eth_account import Account
    from eth_account.messages import encode_defunct, encode_structured_data
except Exception:  # pragma: no cover - optional dependency missing
    Account = None  # type: ignore
    encode_defunct = None  # type: ignore
    encode_structured_data = None  # type: ignore

try:  # pragma: no cover - optional dependency for checksum
    from eth_utils import to_checksum_address
except Exception:  # pragma: no cover - dependency missing
    to_checksum_address = None  # type: ignore

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
LOGGER = logging.getLogger("crypto-loans.backend")


TERMS_VERSION = os.getenv("TERMS_VERSION", "1")
TERMS_TEXT = (
    "Al solicitar este préstamo confirmas que comprendes los riesgos asociados al uso de criptoactivos como colateral, "
    "aceptas la liquidación automática en caso de incumplimiento del LTV pactado y autorizas al coordinador a ejecutar el "
    "colateral si fuese necesario. Declaras que los fondos no proceden de actividades ilícitas y que cumplirás con la "
    "legislación vigente en materia de prevención de blanqueo de capitales.\n"
    "La solicitud queda sujeta a disponibilidad de liquidez en la plataforma y a verificaciones adicionales de seguridad. "
    "El incumplimiento de pagos conlleva cargos adicionales y puede resultar en la liquidación total del colateral aportado."
)
TERMS_HASH = "0x" + hashlib.sha256(TERMS_TEXT.encode("utf-8")).hexdigest()
TERMS_CHAIN_ID = int(os.getenv("TERMS_CHAIN_ID", "43114"))
TERMS_VERIFIER = os.getenv("TERMS_VERIFIER", "0x0000000000000000000000000000000000000000") or "0x0000000000000000000000000000000000000000"
TERMS_DOMAIN_NAME = os.getenv("TERMS_DOMAIN_NAME", "CryptoLoans Terms")


def _checksum_address(value: str) -> str:
    candidate = (value or "0x0000000000000000000000000000000000000000").strip()
    if not candidate:
        candidate = "0x0000000000000000000000000000000000000000"
    if to_checksum_address:
        try:
            return to_checksum_address(candidate)
        except Exception:  # pragma: no cover - checksum conversion failure
            return candidate
    return candidate


TERMS_DOMAIN = {
    "name": TERMS_DOMAIN_NAME,
    "version": TERMS_VERSION,
    "chainId": TERMS_CHAIN_ID,
    "verifyingContract": _checksum_address(TERMS_VERIFIER),
}
TERMS_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "TermsAcceptance": [
        {"name": "wallet", "type": "address"},
        {"name": "termsHash", "type": "bytes32"},
        {"name": "timestamp", "type": "uint256"},
    ],
}


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


def _recover_wallet_from_signature(message: str, signature: str, wallet_hint: Optional[str] = None) -> str:
    signature = str(signature or "").strip()
    if not signature:
        raise APIError(HTTPStatus.BAD_REQUEST, "missing signature")
    wallet_hint_normalized = wallet_hint.strip().lower() if wallet_hint else ""
    if Account and encode_defunct:
        try:
            encoded_message = encode_defunct(text=message)
            recovered = Account.recover_message(encoded_message, signature=signature)
            recovered_normalized = recovered.lower()
        except Exception as exc:
            raise APIError(HTTPStatus.BAD_REQUEST, f"invalid signature: {exc}")
        if wallet_hint_normalized and wallet_hint_normalized != recovered_normalized:
            raise APIError(HTTPStatus.BAD_REQUEST, "signature does not match provided wallet")
        return recovered_normalized
    if not wallet_hint_normalized:
        raise APIError(HTTPStatus.PRECONDITION_REQUIRED, "wallet required to validate signature")
    return wallet_hint_normalized


def _coalesce_address(*candidates: Any) -> str:
    for candidate in candidates:
        if candidate is None:
            continue
        candidate_str = str(candidate).strip()
        if candidate_str and candidate_str.lower() != "none":
            return candidate_str
    return ""


def _validate_terms_acceptance(payload: Dict[str, Any], borrower_wallet: str) -> Dict[str, Any]:
    if not payload:
        raise APIError(HTTPStatus.PRECONDITION_REQUIRED, "terms acceptance is required")
    signature = str(payload.get("signature") or payload.get("termsSignature") or "").strip()
    if not signature:
        raise APIError(HTTPStatus.BAD_REQUEST, "terms acceptance signature missing")
    wallet_candidate = _coalesce_address(payload.get("wallet"), payload.get("address"), borrower_wallet)
    if not wallet_candidate:
        raise APIError(HTTPStatus.PRECONDITION_REQUIRED, "wallet is required for terms acceptance")
    borrower_norm = str(borrower_wallet or "").strip().lower()
    wallet_norm = wallet_candidate.strip().lower()
    if borrower_norm and wallet_norm != borrower_norm:
        raise APIError(HTTPStatus.BAD_REQUEST, "terms acceptance wallet mismatch")
    terms_hash_value = str(payload.get("termsHash") or payload.get("terms_hash") or "").strip()
    if not terms_hash_value:
        raise APIError(HTTPStatus.BAD_REQUEST, "terms hash missing")
    if not terms_hash_value.startswith("0x"):
        terms_hash_value = f"0x{terms_hash_value}"
    if terms_hash_value.lower() != TERMS_HASH.lower():
        raise APIError(HTTPStatus.BAD_REQUEST, "terms hash mismatch")
    provided_version = str(payload.get("termsVersion") or payload.get("version") or TERMS_VERSION)
    if provided_version != TERMS_VERSION:
        raise APIError(HTTPStatus.BAD_REQUEST, "terms version mismatch")
    timestamp_raw = payload.get("timestamp") or payload.get("acceptedAt") or payload.get("accepted_at")
    try:
        timestamp = int(timestamp_raw)
    except (TypeError, ValueError):
        raise APIError(HTTPStatus.BAD_REQUEST, "terms timestamp invalid")
    if timestamp <= 0:
        raise APIError(HTTPStatus.BAD_REQUEST, "terms timestamp invalid")
    if not Account or not encode_structured_data:
        raise APIError(HTTPStatus.PRECONDITION_FAILED, "terms signature validation unavailable")
    domain = dict(TERMS_DOMAIN)
    domain["chainId"] = int(domain.get("chainId", TERMS_CHAIN_ID))
    domain["verifyingContract"] = _checksum_address(domain.get("verifyingContract", TERMS_VERIFIER))
    try:
        wallet_checksum = _checksum_address(wallet_candidate)
    except Exception as exc:  # pragma: no cover - invalid wallet formatting
        raise APIError(HTTPStatus.BAD_REQUEST, f"invalid wallet address: {exc}")
    message = {
        "wallet": wallet_checksum,
        "termsHash": terms_hash_value.lower(),
        "timestamp": timestamp,
    }
    typed_data = {
        "types": TERMS_TYPES,
        "primaryType": "TermsAcceptance",
        "domain": domain,
        "message": message,
    }
    try:
        signable = encode_structured_data(typed_data)
    except Exception as exc:
        raise APIError(HTTPStatus.BAD_REQUEST, f"invalid terms acceptance payload: {exc}")
    try:
        recovered = Account.recover_message(signable, signature=signature)
    except Exception as exc:
        raise APIError(HTTPStatus.BAD_REQUEST, f"invalid terms acceptance signature: {exc}")
    if recovered.strip().lower() != wallet_norm:
        raise APIError(HTTPStatus.BAD_REQUEST, "terms signature does not match wallet")
    return {
        "wallet": wallet_norm,
        "termsHash": terms_hash_value.lower(),
        "timestamp": timestamp,
        "signature": signature,
        "termsVersion": provided_version,
    }


def _flatten_accounts(payload: Any) -> Iterable[Dict[str, Any]]:
    stack = [payload]
    while stack:
        current = stack.pop()
        if current is None:
            continue
        if isinstance(current, dict):
            iban_candidate = current.get("iban") or current.get("ibanNumber")
            if not iban_candidate and isinstance(current.get("account"), dict):
                iban_candidate = current["account"].get("iban")
            if iban_candidate:
                yield current
            for key in ("accounts", "items", "data", "results", "wallets"):
                if key in current:
                    stack.append(current[key])
        elif isinstance(current, (list, tuple, set)):
            stack.extend(current)

def _load_abi(default_filename: str, env_var: str) -> Optional[Iterable[Dict[str, Any]]]:
    """Load a contract ABI from disk, preferring env overrides."""

    path = os.getenv(env_var)
    if path:
        candidate = Path(path)
    else:
        candidate = Path(__file__).resolve().parent / "abi" / default_filename
    if not candidate.exists():
        LOGGER.warning("ABI file missing for %s", default_filename)
        return None
    try:
        with candidate.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:  # pragma: no cover - unexpected file IO failure
        LOGGER.error("Unable to load ABI %s: %s", candidate, exc)
        return None


def _init_web3(url: Optional[str]) -> Optional[Web3]:
    if not Web3 or not url:
        return None
    try:
        provider = Web3.HTTPProvider(url, request_kwargs={"timeout": int(os.getenv("WEB3_TIMEOUT", "15"))})
        web3 = Web3(provider)
        if geth_poa_middleware:
            try:
                web3.middleware_onion.inject(geth_poa_middleware, layer=0)
            except ValueError:  # pragma: no cover - already injected
                pass
        return web3
    except Exception as exc:  # pragma: no cover - connection failures
        LOGGER.error("Failed to initialise web3 provider %s: %s", url, exc)
        return None


def _from_wei(amount: int, decimals: int) -> float:
    return float(amount) / float(10 ** decimals)


def _to_wei(amount: float, decimals: int) -> int:
    return int(round(float(amount) * (10 ** decimals)))


class Web3ContractClient:
    """Lightweight helper around a coordinator contract."""

    def __init__(
        self,
        *,
        name: str,
        url_env: str,
        address_env: str,
        abi_filename: str,
        abi_env: str,
        key_env: str,
    ) -> None:
        self.name = name
        self.web3 = _init_web3(os.getenv(url_env))
        self.abi = _load_abi(abi_filename, abi_env)
        self.address_raw = os.getenv(address_env)
        self.receipt_timeout = int(os.getenv(f"{name.upper()}_RECEIPT_TIMEOUT", "120"))
        self.private_key = os.getenv(key_env)
        self.account_address: Optional[str] = None
        self.contract: Optional[Contract] = None
        if self.web3 and self.abi and self.address_raw:
            try:
                self.account_address = (
                    self.web3.eth.account.from_key(self.private_key).address
                    if self.private_key
                    else None
                )
            except Exception as exc:  # pragma: no cover - invalid key configuration
                LOGGER.error("Invalid %s operator key: %s", name, exc)
                self.private_key = None
                self.account_address = None
            try:
                checksum_address = self.web3.to_checksum_address(self.address_raw)
                self.contract = self.web3.eth.contract(address=checksum_address, abi=self.abi)
            except Exception as exc:  # pragma: no cover - misconfiguration
                LOGGER.error("Failed to bind %s contract: %s", name, exc)
                self.contract = None

    def available(self) -> bool:
        return bool(self.web3 and self.contract)

    def send_transaction(self, function_name: str, *args: Any, value: int = 0) -> Dict[str, Any]:
        if not self.available():
            raise APIError(HTTPStatus.SERVICE_UNAVAILABLE, f"{self.name} coordinator unavailable")
        if not self.private_key or not self.account_address:
            raise APIError(HTTPStatus.PRECONDITION_REQUIRED, f"Missing {self.name} operator key")
        contract_fn = getattr(self.contract.functions, function_name)(*args)
        nonce = self.web3.eth.get_transaction_count(self.account_address)
        tx_params: Dict[str, Any] = {
            "from": self.account_address,
            "nonce": nonce,
            "value": value,
            "gasPrice": self.web3.eth.gas_price,
            "chainId": self.web3.eth.chain_id,
        }
        try:
            gas = contract_fn.estimate_gas(tx_params)
        except Exception as exc:
            raise APIError(HTTPStatus.BAD_REQUEST, f"Gas estimation failed for {self.name}", {"error": str(exc)})
        tx_params["gas"] = gas
        try:
            built = contract_fn.build_transaction(tx_params)
            signed = self.web3.eth.account.sign_transaction(built, private_key=self.private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed.rawTransaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=self.receipt_timeout)
        except Exception as exc:
            raise APIError(HTTPStatus.BAD_GATEWAY, f"{self.name} transaction failed", {"error": str(exc)})
        return {"transactionHash": HexBytes(receipt.transactionHash).hex(), "receipt": receipt}

    def decode_events(self, event_name: str, receipt: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        if not self.available():
            return []
        event_abi = getattr(self.contract.events, event_name, None)
        if not event_abi:
            return []
        try:
            return event_abi().process_receipt(receipt, errors=())
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.error("Failed to decode %s event on %s: %s", event_name, self.name, exc)
            return []


@dataclass
class WorkItem:
    name: str
    callback: Callable[..., Any]
    args: Tuple[Any, ...]
    kwargs: Dict[str, Any]
    attempts: int = 0


class TaskQueue:
    """Retrying background task queue with exponential backoff."""

    def __init__(self, name: str, *, max_retries: int = 5, backoff: float = 5.0) -> None:
        self.name = name
        self.max_retries = max_retries
        self.backoff = backoff
        self._queue: "queue.Queue[WorkItem]" = queue.Queue()
        self._stop_event = threading.Event()
        self._workers: list[threading.Thread] = []
        worker_count = int(os.getenv(f"{name.upper()}_WORKERS", "1"))
        for index in range(worker_count):
            worker = threading.Thread(target=self._run, name=f"{name}-worker-{index}", daemon=True)
            worker.start()
            self._workers.append(worker)

    def submit(self, name: str, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self._queue.put(WorkItem(name=name, callback=callback, args=args, kwargs=kwargs))

    def _run(self) -> None:  # pragma: no cover - background worker
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                item.callback(*item.args, **item.kwargs)
            except Exception as exc:
                item.attempts += 1
                if item.attempts <= self.max_retries:
                    delay = self.backoff * item.attempts
                    LOGGER.warning(
                        "%s task %s failed (%s), retrying in %.1fs (attempt %s/%s)",
                        self.name,
                        item.name,
                        exc,
                        delay,
                        item.attempts,
                        self.max_retries,
                    )
                    time.sleep(delay)
                    self._queue.put(item)
                else:
                    LOGGER.error("%s task %s failed permanently: %s", self.name, item.name, exc)
            finally:
                self._queue.task_done()

    def stop(self) -> None:
        self._stop_event.set()


class EventWorker(threading.Thread):
    """Polls on-chain events and dispatches handlers."""

    def __init__(
        self,
        *,
        name: str,
        client: Web3ContractClient,
        event_name: str,
        handler: Callable[[Dict[str, Any], Dict[str, Any]], None],
        start_block: Optional[int] = None,
        interval: int = 15,
    ) -> None:
        super().__init__(daemon=True, name=f"{name}-{event_name}")
        self.client = client
        self.event_name = event_name
        self.handler = handler
        self.interval = interval
        self._stop_event = threading.Event()
        self._last_block = start_block

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:  # pragma: no cover - background loop
        if not self.client.available():
            LOGGER.info("Skipping event worker %s - client unavailable", self.event_name)
            return
        LOGGER.info("Event worker %s started", self.event_name)
        while not self._stop_event.is_set():
            try:
                latest = self.client.web3.eth.block_number
                if self._last_block is None:
                    self._last_block = latest
                if latest < self._last_block:
                    time.sleep(self.interval)
                    continue
                if latest == self._last_block:
                    time.sleep(self.interval)
                    continue
                event_abi = getattr(self.client.contract.events, self.event_name, None)
                if not event_abi:
                    LOGGER.warning("Event %s missing on %s", self.event_name, self.client.name)
                    time.sleep(self.interval)
                    continue
                from_block = self._last_block + 1
                logs = event_abi().get_logs(fromBlock=from_block, toBlock=latest)
                for log in logs:
                    try:
                        self.handler(log["args"], log)
                    except Exception as exc:
                        LOGGER.exception("Event handler %s failed: %s", self.event_name, exc)
                self._last_block = latest
            except Exception as exc:
                LOGGER.error("Event worker %s error: %s", self.event_name, exc)
            finally:
                time.sleep(self.interval)
        LOGGER.info("Event worker %s stopped", self.event_name)


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

    def verify_user_iban(self, monerium_user_id: str, iban: str) -> Dict[str, Any]:
        normalized_iban = normalize_iban(iban)
        if not monerium_user_id:
            raise APIError(HTTPStatus.BAD_REQUEST, "Missing Monerium user identifier")
        path = f"/users/{urllib.parse.quote(monerium_user_id)}/accounts"
        try:
            payload = self._authorized_request("GET", path)
        except APIError as exc:
            if exc.status == HTTPStatus.NOT_FOUND:
                raise APIError(HTTPStatus.NOT_FOUND, "Monerium user not found", {"moneriumUserId": monerium_user_id})
            raise
        for entry in _flatten_accounts(payload):
            candidate = entry.get("iban") or entry.get("ibanNumber")
            if not candidate and isinstance(entry.get("account"), dict):
                candidate = entry["account"].get("iban")
            if candidate and normalize_iban(candidate) == normalized_iban:
                return entry
        raise APIError(
            HTTPStatus.BAD_REQUEST,
            "IBAN not associated with Monerium user",
            {"iban": normalized_iban, "moneriumUserId": monerium_user_id},
        )


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
BTCB_DECIMALS = int(os.getenv("BTCB_DECIMALS", "8"))
EURE_DECIMALS = int(os.getenv("EURE_DECIMALS", "18"))

AVALANCHE_COORDINATOR = Web3ContractClient(
    name="avalanche",
    url_env="AVALANCHE_RPC_URL",
    address_env="AVALANCHE_COORDINATOR_ADDRESS",
    abi_filename="AvalancheLoanCoordinator.json",
    abi_env="AVALANCHE_COORDINATOR_ABI",
    key_env="AVALANCHE_OPERATOR_KEY",
)
ETHEREUM_COORDINATOR = Web3ContractClient(
    name="ethereum",
    url_env="ETHEREUM_RPC_URL",
    address_env="ETHEREUM_COORDINATOR_ADDRESS",
    abi_filename="EthereumLoanCoordinator.json",
    abi_env="ETHEREUM_COORDINATOR_ABI",
    key_env="ETHEREUM_OPERATOR_KEY",
)

MONERIUM_QUEUE = TaskQueue("monerium")
BRIDGE_QUEUE = TaskQueue("bridge")
EVENT_WORKERS: list[EventWorker] = []


def _loan_id_hex(value: Any) -> str:
    if isinstance(value, str):
        return value if value.startswith("0x") else f"0x{value}"
    try:
        return HexBytes(value).hex()
    except Exception:
        if Web3:
            return Web3.to_hex(value)
        raise


def _loan_id_bytes(value: str) -> bytes:
    raw = HexBytes(value)
    if len(raw) < 32:
        raw = raw.rjust(32, b"\x00")
    return bytes(raw)


def _encode_bytes(data: Any) -> str:
    if isinstance(data, (bytes, bytearray)):
        return base64.b64encode(bytes(data)).decode("ascii")
    if isinstance(data, str):
        return data
    return base64.b64encode(json.dumps(data).encode("utf-8")).decode("ascii")


def _execute_monerium_redeem(loan_id: str, iban: str, amount: float, reference: str) -> None:
    result = MONERIUM.redeem(iban, amount, reference)
    STORE.update(loan_id, moneriumRedeem=result)
    STORE.record_event(loan_id, "monerium-redeem", {"amount": amount, "reference": reference})


def _execute_bridge_release(loan_id: str, btc_recipient: str, bridge_params: str) -> None:
    loan = STORE.get(loan_id) or {}
    collateral = float(loan.get("collateralBTCb") or 0)
    if collateral <= 0:
        raise ValueError("unknown collateral amount")
    network = os.getenv("AVALANCHE_BRIDGE_NETWORK", "mainnet")
    source_address = loan.get("bridgeSourceAddress") or loan.get("bridge", {}).get("sourceAddress") if isinstance(loan.get("bridge"), dict) else loan.get("bridgeSource", "")
    if not source_address:
        source_address = os.getenv("AVALANCHE_BRIDGE_SOURCE", "")
    result = BRIDGE.initiate_unwrap(collateral, btc_recipient, source_address, network)
    STORE.record_event(
        loan_id,
        "collateral-release-processed",
        {"btcRecipient": btc_recipient, "bridgeParams": bridge_params, "result": result},
    )


def _handle_repayment_recorded(args: Dict[str, Any], log: Dict[str, Any]) -> None:
    loan_id = _loan_id_hex(args.get("loanId"))
    amount_eure = _from_wei(int(args.get("amountEURe", 0)), EURE_DECIMALS)
    via_monerium = bool(args.get("viaMonerium"))
    payer = args.get("payer")
    STORE.record_event(
        loan_id,
        "repayment-recorded-onchain",
        {"amount": amount_eure, "viaMonerium": via_monerium, "payer": payer},
    )
    STORE.mark_repaid(loan_id, amount_eure)
    loan = STORE.get(loan_id) or {}
    iban = loan.get("iban") if via_monerium else None
    if not iban and loan.get("disburseVia") == "monerium":
        iban = loan.get("iban")
    if iban:
        reference = loan.get("reference") or f"Loan {loan_id} repayment"
        MONERIUM_QUEUE.submit(
            f"monerium-redeem-{loan_id}",
            _execute_monerium_redeem,
            loan_id,
            iban,
            amount_eure,
            reference,
        )


def _handle_collateral_release_requested(args: Dict[str, Any], log: Dict[str, Any]) -> None:
    loan_id = _loan_id_hex(args.get("loanId"))
    btc_recipient = args.get("btcRecipient")
    bridge_params = args.get("bridgeParams")
    encoded_params = _encode_bytes(bridge_params)
    STORE.record_event(
        loan_id,
        "collateral-release-requested",
        {"btcRecipient": btc_recipient, "bridgeParams": encoded_params},
    )
    if btc_recipient:
        BRIDGE_QUEUE.submit(
            f"bridge-release-{loan_id}",
            _execute_bridge_release,
            loan_id,
            btc_recipient,
            encoded_params,
        )


def _handle_liquidation_triggered(args: Dict[str, Any], log: Dict[str, Any]) -> None:
    loan_id = _loan_id_hex(args.get("loanId"))
    amount = _from_wei(int(args.get("amountBTCb", 0)), BTCB_DECIMALS)
    user = args.get("user")
    STORE.record_event(
        loan_id,
        "liquidation-triggered",
        {"amountBTCb": amount, "user": user},
    )
    STORE.mark_default(loan_id, "liquidation", amount)


def _handle_loan_registered(args: Dict[str, Any], log: Dict[str, Any]) -> None:
    loan_id = _loan_id_hex(args.get("loanId"))
    collateral = _from_wei(int(args.get("collateralBTCb", 0)), BTCB_DECIMALS)
    principal = _from_wei(int(args.get("principalEUR", 0)), EURE_DECIMALS)
    deadline = int(args.get("deadline", 0))
    user = args.get("user")
    payload = {
        "loanId": loan_id,
        "principal": principal,
        "collateralBTCb": collateral,
        "deadline": deadline,
        "borrower": user,
        "status": "active",
    }
    existing = STORE.get(loan_id)
    if existing:
        STORE.update(loan_id, **payload)
    else:
        STORE.create(payload)
    STORE.record_event(
        loan_id,
        "loan-registered-onchain",
        {"principal": principal, "collateralBTCb": collateral, "deadline": deadline, "user": user},
    )


def _start_event_workers() -> None:
    if EVENT_WORKERS:
        return
    if ETHEREUM_COORDINATOR.available():
        EVENT_WORKERS.append(
            EventWorker(
                name="ethereum",
                client=ETHEREUM_COORDINATOR,
                event_name="RepaymentRecorded",
                handler=_handle_repayment_recorded,
                interval=int(os.getenv("ETH_EVENT_INTERVAL", "20")),
            )
        )
        EVENT_WORKERS.append(
            EventWorker(
                name="ethereum",
                client=ETHEREUM_COORDINATOR,
                event_name="CollateralReleaseRequested",
                handler=_handle_collateral_release_requested,
                interval=int(os.getenv("ETH_EVENT_INTERVAL", "20")),
            )
        )
        EVENT_WORKERS.append(
            EventWorker(
                name="ethereum",
                client=ETHEREUM_COORDINATOR,
                event_name="LoanRegistered",
                handler=_handle_loan_registered,
                interval=int(os.getenv("ETH_EVENT_INTERVAL", "20")),
            )
        )
    if AVALANCHE_COORDINATOR.available():
        EVENT_WORKERS.append(
            EventWorker(
                name="avalanche",
                client=AVALANCHE_COORDINATOR,
                event_name="LiquidationTriggered",
                handler=_handle_liquidation_triggered,
                interval=int(os.getenv("AVAX_EVENT_INTERVAL", "20")),
            )
        )
    for worker in EVENT_WORKERS:
        worker.start()


def _handle_monerium_link(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        iban = str(payload["iban"]).strip()
        monerium_user_id = str(payload["moneriumUserId"]).strip()
        signature = str(payload["signature"]).strip()
    except KeyError as exc:
        raise APIError(HTTPStatus.BAD_REQUEST, f"missing field {exc.args[0]}")
    message = str(payload.get("message") or "").strip()
    if not message:
        raise APIError(HTTPStatus.BAD_REQUEST, "missing message")
    wallet_hint = (
        payload.get("wallet")
        or payload.get("walletAddress")
        or payload.get("address")
        or payload.get("borrower")
    )
    wallet = _recover_wallet_from_signature(message, signature, wallet_hint)
    metadata = MONERIUM.verify_user_iban(monerium_user_id, iban)
    try:
        record = STORE.link_monerium_wallet(
            wallet,
            iban,
            monerium_user_id,
            signature,
            message=message,
            metadata=metadata if isinstance(metadata, dict) else {},
        )
    except ValueError as exc:
        raise APIError(HTTPStatus.BAD_REQUEST, str(exc))
    record.setdefault("status", "linked")
    return record


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
        if parsed.path == "/terms":
            self._json(
                HTTPStatus.OK,
                {"data": {"text": TERMS_TEXT, "hash": TERMS_HASH, "version": TERMS_VERSION, "domain": TERMS_DOMAIN}},
            )
            return
        if parsed.path.startswith("/terms/"):
            parts = parsed.path.split("/")
            if len(parts) < 3 or not parts[2]:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "missing wallet"})
                return
            wallet = parts[2]
            record = STORE.get_terms_acceptance(wallet)
            if not record:
                self._json(HTTPStatus.NOT_FOUND, {"error": "terms acceptance not found"})
                return
            self._json(HTTPStatus.OK, {"data": record})
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
        if parsed.path.startswith("/monerium/link/"):
            parts = parsed.path.split("/")
            if len(parts) < 4 or not parts[3]:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "missing wallet"})
                return
            wallet = parts[3]
            record = STORE.get_monerium_link(wallet)
            if not record:
                self._json(HTTPStatus.NOT_FOUND, {"error": "monerium link not found"})
                return
            self._json(HTTPStatus.OK, {"data": record})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in {"/health"} and (not self._rate_limit() or not self._ensure_authorized()):
            return
        payload = self._read_json()
        try:
            if parsed.path == "/monerium/link":
                record = _handle_monerium_link(payload)
                self._json(HTTPStatus.OK, {"data": record})
                return
            if parsed.path == "/loans":
                loan = self._handle_create_loan(payload)
                self._json(HTTPStatus.CREATED, {"data": loan})
                return
            if parsed.path == "/repay":
                loan_id = str(payload.get("loanId"))
                amount = float(payload.get("amount", 0))
                via = payload.get("via", "manual")
                binding_record: Optional[Dict[str, Any]] = None
                if via == "iban":
                    loan_record = STORE.get(loan_id)
                    if not loan_record:
                        raise APIError(HTTPStatus.NOT_FOUND, "loan not found for repayment")
                    borrower = loan_record.get("borrower") or loan_record.get("user")
                    if not borrower:
                        raise APIError(HTTPStatus.PRECONDITION_REQUIRED, "loan missing borrower information")
                    try:
                        binding_record = STORE.require_monerium_link(str(borrower))
                    except ValueError as exc:
                        raise APIError(HTTPStatus.PRECONDITION_REQUIRED, str(exc))
                loan = STORE.mark_repaid(loan_id, amount)
                metadata = {"amount": amount, "via": via}
                if binding_record:
                    metadata["bindingHash"] = binding_record.get("bindingHash")
                STORE.record_event(loan_id, "repayment-submitted", metadata)
                self._json(HTTPStatus.OK, {"data": loan})
                return
            if parsed.path == "/monerium/redeem":
                wallet = payload.get("wallet") or payload.get("walletAddress") or payload.get("address")
                if not wallet:
                    raise APIError(HTTPStatus.PRECONDITION_REQUIRED, "wallet is required for Monerium redeem")
                try:
                    binding = STORE.require_monerium_link(wallet, iban=payload["iban"])
                except ValueError as exc:
                    raise APIError(HTTPStatus.PRECONDITION_REQUIRED, str(exc))
                result = MONERIUM.redeem(
                    payload["iban"],
                    float(payload.get("amount", 0)),
                    payload.get("reference", "Loan payout"),
                )
                result.setdefault("bindingHash", binding.get("bindingHash"))
                self._json(HTTPStatus.OK, {"data": result})
                return
            if parsed.path == "/monerium/issue":
                wallet = payload.get("address") or payload.get("wallet")
                if not wallet:
                    raise APIError(HTTPStatus.PRECONDITION_REQUIRED, "wallet is required for Monerium issue")
                try:
                    binding = STORE.require_monerium_link(wallet)
                except ValueError as exc:
                    raise APIError(HTTPStatus.PRECONDITION_REQUIRED, str(exc))
                result = MONERIUM.issue_eure(wallet, float(payload.get("amount", 0)))
                result.setdefault("bindingHash", binding.get("bindingHash"))
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
        ltv_percent = float(payload.get("ltv", 0))
        if not principal or not collateral:
            raise ValueError("principal and collateralBTCb are required")
        if ltv_percent <= 0 or ltv_percent > 70:
            raise ValueError("ltv must be between 0 and 70")
        duration = int(payload.get("duration", 0))
        if duration <= 0:
            raise ValueError("duration must be greater than zero")

        borrower_wallet = _coalesce_address(
            payload.get("borrower"),
            payload.get("beneficiary"),
            payload.get("beneficiaryAddress"),
            payload.get("eureWallet"),
        )
        if not borrower_wallet:
            raise APIError(HTTPStatus.PRECONDITION_REQUIRED, "borrower wallet is required")

        ltv_bps = int(payload.get("ltvBps") or round(ltv_percent * 100))
        collateral_raw = int(payload.get("collateralRaw") or _to_wei(collateral, BTCB_DECIMALS))
        principal_raw = int(payload.get("principalRaw") or _to_wei(principal, EURE_DECIMALS))
        bridge_proof_value = payload.get("bridgeProof", b"")
        if isinstance(bridge_proof_value, str):
            bridge_proof_value = bridge_proof_value.strip()
            if bridge_proof_value:
                try:
                    bridge_proof = base64.b64decode(bridge_proof_value)
                except binascii.Error as exc:
                    raise ValueError("invalid bridgeProof encoding") from exc
            else:
                bridge_proof = b""
        elif isinstance(bridge_proof_value, (bytes, bytearray)):
            bridge_proof = bytes(bridge_proof_value)
        else:
            bridge_proof = b""

        pending_events: list[Tuple[str, Dict[str, Any]]] = []
        loan_metadata: Dict[str, Any] = dict(payload)
        loan_metadata["borrower"] = borrower_wallet
        terms_payload = dict(payload.get("termsAcceptance") or {})
        if "signature" not in terms_payload and payload.get("termsSignature"):
            terms_payload["signature"] = payload["termsSignature"]
        validated_terms = _validate_terms_acceptance(terms_payload, borrower_wallet)
        sanitized_terms = {
            "wallet": validated_terms["wallet"],
            "termsHash": validated_terms["termsHash"],
            "timestamp": validated_terms["timestamp"],
            "termsVersion": validated_terms["termsVersion"],
        }
        loan_metadata["termsAcceptance"] = sanitized_terms
        loan_metadata["termsAcceptedAt"] = validated_terms["timestamp"]
        loan_metadata["termsAcceptedHash"] = validated_terms["termsHash"]
        loan_metadata["termsSignature"] = validated_terms["signature"]
        STORE.record_terms_acceptance(
            validated_terms["wallet"],
            validated_terms["termsHash"],
            validated_terms["signature"],
            message=sanitized_terms,
            accepted_at=validated_terms["timestamp"],
        )
        pending_events.append(
            (
                "terms-accepted",
                {
                    "termsHash": validated_terms["termsHash"],
                    "timestamp": validated_terms["timestamp"],
                    "termsVersion": validated_terms["termsVersion"],
                },
            )
        )
        monerium_binding: Optional[Dict[str, Any]] = None
        loan_id: Optional[str] = loan_metadata.get("loanId")
        avalanche_tx_hash: Optional[str] = None
        ethereum_tx_hash: Optional[str] = None

        if payload.get("disburseVia") == "monerium" and payload.get("iban"):
            try:
                monerium_binding = STORE.require_monerium_link(str(borrower_wallet), iban=payload["iban"])
            except ValueError as exc:
                raise APIError(HTTPStatus.PRECONDITION_REQUIRED, str(exc))
            loan_metadata["moneriumLinkHash"] = monerium_binding.get("bindingHash")

        if AVALANCHE_COORDINATOR.available():
            response = AVALANCHE_COORDINATOR.send_transaction(
                "depositCollateral",
                collateral_raw,
                ltv_bps,
                duration,
                bridge_proof,
            )
            receipt = response["receipt"]
            events = list(AVALANCHE_COORDINATOR.decode_events("CollateralDeposited", receipt))
            if not events:
                raise APIError(HTTPStatus.BAD_GATEWAY, "Collateral deposit confirmation missing")
            deposit_event = events[0]["args"]
            loan_id = _loan_id_hex(deposit_event.get("loanId"))
            collateral_raw = int(deposit_event.get("amountBTCb", collateral_raw))
            principal_raw = int(deposit_event.get("principalEUR", principal_raw))
            avalanche_tx_hash = response["transactionHash"]
            pending_events.append(
                (
                    "collateral-deposit-confirmed",
                    {
                        "transactionHash": avalanche_tx_hash,
                        "amountBTCb": _from_wei(collateral_raw, BTCB_DECIMALS),
                        "principalEUR": _from_wei(principal_raw, EURE_DECIMALS),
                        "ltvBps": int(deposit_event.get("ltvBps", ltv_bps)),
                        "deadline": int(deposit_event.get("deadline", duration)),
                    },
                )
            )

        if not loan_id:
            loan_id = f"loan-{int(time.time() * 1000)}"

        if ETHEREUM_COORDINATOR.available():
            if not str(loan_id).startswith("0x"):
                raise APIError(HTTPStatus.PRECONDITION_FAILED, "Unable to fund loan without on-chain identifier")
            beneficiary = payload.get("beneficiary") or payload.get("beneficiaryAddress") or payload.get("eureWallet")
            checksum_beneficiary = "0x0000000000000000000000000000000000000000"
            if beneficiary:
                checksum_beneficiary = ETHEREUM_COORDINATOR.web3.to_checksum_address(beneficiary)
            response = ETHEREUM_COORDINATOR.send_transaction(
                "fundLoan",
                _loan_id_bytes(loan_id),
                checksum_beneficiary,
            )
            ethereum_tx_hash = response["transactionHash"]
            events = list(ETHEREUM_COORDINATOR.decode_events("LoanFunded", response["receipt"]))
            if events:
                funded_event = events[0]["args"]
                amount_eure = _from_wei(int(funded_event.get("amountEURe", principal_raw)), EURE_DECIMALS)
                pending_events.append(
                    (
                        "loan-funded-confirmed",
                        {
                            "transactionHash": ethereum_tx_hash,
                            "beneficiary": funded_event.get("beneficiary"),
                            "amountEURe": amount_eure,
                        },
                    )
                )

        principal = _from_wei(principal_raw, EURE_DECIMALS)
        collateral = _from_wei(collateral_raw, BTCB_DECIMALS)
        loan_metadata.update(
            {
                "loanId": loan_id,
                "principal": principal,
                "collateralBTCb": collateral,
                "ltv": ltv_percent,
                "ltvBps": ltv_bps,
                "duration": duration,
                "avalancheTxHash": avalanche_tx_hash,
                "ethereumTxHash": ethereum_tx_hash,
            }
        )
        loan = STORE.create(loan_metadata)
        STORE.record_event(
            loan_id,
            "loan-validated",
            {"principal": principal, "collateral": collateral, "ltv": ltv_percent},
        )
        for event_name, metadata in pending_events:
            STORE.record_event(loan_id, event_name, metadata)

        if payload.get("disburseVia") == "monerium" and payload.get("iban"):
            payout = MONERIUM.redeem(payload["iban"], principal, payload.get("reference", "Loan disbursement"))
            update_fields: Dict[str, Any] = {"moneriumPayout": payout}
            if monerium_binding:
                update_fields.setdefault("moneriumLinkHash", monerium_binding.get("bindingHash"))
            loan = STORE.update(loan_id, **update_fields)
            event_metadata = {"provider": "monerium"}
            if monerium_binding:
                event_metadata["bindingHash"] = monerium_binding.get("bindingHash")
            STORE.record_event(loan_id, "payout-executed", event_metadata)
        return loan


def run(port: int = 8080) -> None:
    if not RISK_MONITOR.is_alive():
        RISK_MONITOR.start()
    _start_event_workers()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    LOGGER.info("Crypto Loans backend listening on http://0.0.0.0:%s", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - manual stop
        LOGGER.info("Shutting down due to interrupt")
    finally:
        RISK_MONITOR.stop()
        for worker in EVENT_WORKERS:
            worker.stop()
        for worker in EVENT_WORKERS:
            worker.join(timeout=5)
        MONERIUM_QUEUE.stop()
        BRIDGE_QUEUE.stop()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    run()
