"""Persistent loan store backed by SQLite with audit logging."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, Iterable, List, Optional


def normalize_iban(iban: str) -> str:
    return "".join(iban.split()).upper()


def _json_dumps(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _json_loads(raw: str) -> Dict[str, Any]:
    return json.loads(raw) if raw else {}


class LoanStore:
    """Thread-safe persistent store keeping track of loans and their history."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or os.getenv("LOANSTORE_PATH", "./data/loans.db")
        os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._lock = threading.Lock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._conn:  # type: ignore[call-arg]
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS loans (
                    loan_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    loan_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    metadata TEXT,
                    timestamp INTEGER NOT NULL,
                    FOREIGN KEY (loan_id) REFERENCES loans (loan_id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_events_loan ON events(loan_id)
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS monerium_links (
                    wallet TEXT PRIMARY KEY,
                    iban TEXT NOT NULL,
                    monerium_user_id TEXT NOT NULL,
                    binding_hash TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    message TEXT,
                    metadata TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_monerium_links_hash
                ON monerium_links(binding_hash)
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS terms_acceptance (
                    wallet TEXT PRIMARY KEY,
                    terms_hash TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    message TEXT,
                    accepted_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_terms_acceptance_hash
                ON terms_acceptance(terms_hash)
                """
            )

    def _fetch(self, loan_id: str) -> Optional[Dict[str, Any]]:
        cursor = self._conn.execute("SELECT data FROM loans WHERE loan_id = ?", (loan_id,))
        row = cursor.fetchone()
        return _json_loads(row[0]) if row else None

    def _persist(self, loan_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        encoded = _json_dumps(payload)
        with self._conn:  # type: ignore[call-arg]
            self._conn.execute(
                "INSERT INTO loans(loan_id, data) VALUES(?, ?)\n                 ON CONFLICT(loan_id) DO UPDATE SET data = excluded.data",
                (loan_id, encoded),
            )
        return dict(payload)

    def _list_ids(self) -> Iterable[str]:
        cursor = self._conn.execute("SELECT loan_id FROM loans ORDER BY loan_id")
        for row in cursor.fetchall():
            yield row[0]

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            loan_id = str(payload.get("loanId") or payload.get("loan_id"))
            if not loan_id:
                loan_id = f"loan-{int(time.time() * 1000)}"
            record = dict(payload)
            record["loanId"] = loan_id
            record.setdefault("status", "active")
            record.setdefault("createdAt", int(time.time()))
            record.setdefault("history", [])
            record.setdefault("ltv", float(payload.get("ltv", 0)))
            record.setdefault("principal", float(payload.get("principal", 0)))
            record.setdefault("collateralBTCb", float(payload.get("collateralBTCb", 0)))
            stored = self._persist(loan_id, record)
            self.record_event(loan_id, "loan-created", {"principal": stored.get("principal"), "ltv": stored.get("ltv")})
            return stored

    def list(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {loan_id: self._fetch(loan_id) or {} for loan_id in self._list_ids()}

    def get(self, loan_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            loan = self._fetch(loan_id)
            if not loan:
                return None
            loan["history"] = self._events_for(loan_id)
            return loan

    def update(self, loan_id: str, **fields: Any) -> Dict[str, Any]:
        with self._lock:
            loan = self._fetch(loan_id) or {"loanId": loan_id, "history": []}
            loan.update(fields)
            return self._persist(loan_id, loan)

    def record_event(self, loan_id: str, event: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        metadata = metadata or {}
        timestamp = int(time.time())
        with self._conn:  # type: ignore[call-arg]
            self._conn.execute(
                "INSERT INTO events(loan_id, event, metadata, timestamp) VALUES(?, ?, ?, ?)",
                (loan_id, event, _json_dumps(metadata), timestamp),
            )
        return {"event": event, "metadata": metadata, "timestamp": timestamp}

    def _events_for(self, loan_id: str) -> List[Dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT event, metadata, timestamp FROM events WHERE loan_id = ? ORDER BY id ASC",
            (loan_id,),
        )
        events = []
        for event, metadata, ts in cursor.fetchall():
            events.append({"event": event, "metadata": _json_loads(metadata), "timestamp": ts})
        return events

    def _fetch_monerium_link(self, wallet: str) -> Optional[Dict[str, Any]]:
        cursor = self._conn.execute(
            """
            SELECT wallet, iban, monerium_user_id, binding_hash, signature, message, metadata, created_at, updated_at
            FROM monerium_links WHERE wallet = ?
            """,
            (wallet.lower(),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        metadata = _json_loads(row[6]) if row[6] else {}
        return {
            "wallet": row[0],
            "iban": row[1],
            "moneriumUserId": row[2],
            "bindingHash": row[3],
            "signature": row[4],
            "message": row[5],
            "metadata": metadata,
            "createdAt": int(row[7]),
            "updatedAt": int(row[8]),
            "status": "linked",
        }

    def _fetch_terms_acceptance(self, wallet: str) -> Optional[Dict[str, Any]]:
        cursor = self._conn.execute(
            """
            SELECT wallet, terms_hash, signature, message, accepted_at, updated_at
            FROM terms_acceptance WHERE wallet = ?
            """,
            (wallet,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        message = _json_loads(row[3]) if row[3] else {}
        record = {
            "wallet": row[0],
            "termsHash": row[1],
            "signature": row[2],
            "message": message,
            "acceptedAt": int(row[4]),
            "updatedAt": int(row[5]),
            "status": "accepted",
        }
        return record

    def link_monerium_wallet(
        self,
        wallet: str,
        iban: str,
        monerium_user_id: str,
        signature: str,
        *,
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        wallet_norm = wallet.strip().lower()
        iban_norm = normalize_iban(iban)
        user_norm = monerium_user_id.strip()
        if not wallet_norm:
            raise ValueError("wallet is required")
        if not iban_norm:
            raise ValueError("iban is required")
        if not user_norm:
            raise ValueError("monerium_user_id is required")
        metadata = metadata or {}
        timestamp = int(time.time())
        digest = hashlib.sha256()
        digest.update(wallet_norm.encode("utf-8"))
        digest.update(iban_norm.encode("utf-8"))
        digest.update(user_norm.encode("utf-8"))
        binding_hash = digest.hexdigest()
        metadata_json = _json_dumps(metadata)
        with self._lock:
            existing = self._fetch_monerium_link(wallet_norm)
            created_at = existing["createdAt"] if existing else timestamp
            with self._conn:  # type: ignore[call-arg]
                self._conn.execute(
                    """
                    INSERT INTO monerium_links(
                        wallet, iban, monerium_user_id, binding_hash, signature, message, metadata, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(wallet) DO UPDATE SET
                        iban = excluded.iban,
                        monerium_user_id = excluded.monerium_user_id,
                        binding_hash = excluded.binding_hash,
                        signature = excluded.signature,
                        message = excluded.message,
                        metadata = excluded.metadata,
                        updated_at = excluded.updated_at
                    """,
                    (
                        wallet_norm,
                        iban_norm,
                        user_norm,
                        binding_hash,
                        signature,
                        message,
                        metadata_json,
                        created_at,
                        timestamp,
                    ),
                )
        record = self.get_monerium_link(wallet_norm) or {}
        return record

    def get_monerium_link(self, wallet: str) -> Optional[Dict[str, Any]]:
        wallet_norm = wallet.strip().lower()
        with self._lock:
            return self._fetch_monerium_link(wallet_norm)

    def record_terms_acceptance(
        self,
        wallet: str,
        terms_hash: str,
        signature: str,
        *,
        message: Optional[Dict[str, Any]] = None,
        accepted_at: Optional[int] = None,
    ) -> Dict[str, Any]:
        wallet_norm = wallet.strip().lower()
        if not wallet_norm:
            raise ValueError("wallet is required")
        hash_value = (terms_hash or "").strip().lower()
        if not hash_value:
            raise ValueError("terms_hash is required")
        if not hash_value.startswith("0x"):
            hash_value = f"0x{hash_value}"
        payload = dict(message or {})
        timestamp = int(accepted_at or payload.get("timestamp") or time.time())
        payload.setdefault("wallet", wallet_norm)
        payload.setdefault("termsHash", hash_value)
        payload.setdefault("timestamp", timestamp)
        encoded_message = _json_dumps(payload)
        updated_at = int(time.time())
        with self._lock:
            with self._conn:  # type: ignore[call-arg]
                self._conn.execute(
                    """
                    INSERT INTO terms_acceptance(wallet, terms_hash, signature, message, accepted_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(wallet) DO UPDATE SET
                        terms_hash = excluded.terms_hash,
                        signature = excluded.signature,
                        message = excluded.message,
                        accepted_at = excluded.accepted_at,
                        updated_at = excluded.updated_at
                    """,
                    (wallet_norm, hash_value, signature, encoded_message, timestamp, updated_at),
                )
        return self.get_terms_acceptance(wallet_norm) or {}

    def get_terms_acceptance(self, wallet: str) -> Optional[Dict[str, Any]]:
        wallet_norm = wallet.strip().lower()
        if not wallet_norm:
            return None
        with self._lock:
            return self._fetch_terms_acceptance(wallet_norm)

    def require_monerium_link(
        self,
        wallet: str,
        *,
        iban: Optional[str] = None,
        monerium_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        record = self.get_monerium_link(wallet)
        if not record:
            raise ValueError("monerium link not found")
        if iban and normalize_iban(iban) != record.get("iban"):
            raise ValueError("iban does not match linked account")
        if monerium_user_id and monerium_user_id.strip() != record.get("moneriumUserId"):
            raise ValueError("monerium user id does not match linked account")
        return record

    def mark_repaid(self, loan_id: str, amount: float) -> Dict[str, Any]:
        with self._lock:
            loan = self._fetch(loan_id)
            if not loan:
                loan = {"loanId": loan_id, "history": []}
            loan["status"] = "repaid"
            loan["repaidAmount"] = float(amount)
            loan["repaidAt"] = int(time.time())
            stored = self._persist(loan_id, loan)
        self.record_event(loan_id, "repayment-recorded", {"amount": amount})
        return stored

    def mark_default(self, loan_id: str, reason: str, ltv: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            loan = self._fetch(loan_id) or {"loanId": loan_id, "history": []}
            loan["status"] = "defaulted"
            loan["defaultReason"] = reason
            if ltv is not None:
                loan["currentLtv"] = ltv
            stored = self._persist(loan_id, loan)
        self.record_event(loan_id, "loan-defaulted", {"reason": reason, "ltv": ltv})
        return stored

    def update_health(self, loan_id: str, *, price_eur: float, ltv: float) -> Dict[str, Any]:
        with self._lock:
            loan = self._fetch(loan_id)
            if not loan:
                return {}
            loan["lastPriceEur"] = price_eur
            loan["currentLtv"] = ltv
            loan["healthUpdatedAt"] = int(time.time())
            stored = self._persist(loan_id, loan)
        self.record_event(loan_id, "health-check", {"priceEur": price_eur, "ltv": ltv})
        return stored

    def history(self, loan_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return self._events_for(loan_id)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = ["LoanStore", "normalize_iban"]
