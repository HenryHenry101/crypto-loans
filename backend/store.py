"""Persistent loan store backed by SQLite with audit logging."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, Iterable, List, Optional


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


__all__ = ["LoanStore"]
