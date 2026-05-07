from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any

from backtest.core.orders import ExecutionReport, OrderIntent


class SQLiteOrderLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def record_intent(self, intent: OrderIntent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO orders
                (
                    account_id, client_order_id, strategy_id, instrument_id, side,
                    quantity, order_type, limit_price, time_in_force, status,
                    created_at, reason, broker_order_id, filled_quantity,
                    avg_fill_price, reported_at, error, raw_response
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.account_id,
                    intent.client_order_id,
                    intent.strategy_id,
                    intent.instrument_id,
                    intent.side.value,
                    str(intent.quantity),
                    intent.order_type.value,
                    str(intent.limit_price) if intent.limit_price is not None else None,
                    intent.time_in_force.value,
                    "created",
                    intent.created_at.isoformat(),
                    intent.reason,
                    None,
                    "0",
                    None,
                    None,
                    "",
                    "{}",
                ),
            )

    def record_report(self, report: ExecutionReport) -> None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE orders
                SET status = ?,
                    broker_order_id = ?,
                    filled_quantity = ?,
                    avg_fill_price = ?,
                    reported_at = ?,
                    error = ?,
                    raw_response = ?
                WHERE account_id = ? AND client_order_id = ?
                """,
                (
                    report.status.value,
                    report.broker_order_id,
                    str(report.filled_quantity),
                    str(report.avg_fill_price) if report.avg_fill_price is not None else None,
                    report.reported_at.isoformat(),
                    report.error,
                    json.dumps(report.raw_response, sort_keys=True),
                    report.account_id,
                    report.client_order_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Order intent not found: {report.account_id}/{report.client_order_id}")

    def get_order(self, account_id: str, client_order_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM orders
                WHERE account_id = ? AND client_order_id = ?
                """,
                (account_id, client_order_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_orders(self, account_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM orders
                WHERE account_id = ?
                ORDER BY created_at, client_order_id
                """,
                (account_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    account_id TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    instrument_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    limit_price TEXT,
                    time_in_force TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    broker_order_id TEXT,
                    filled_quantity TEXT NOT NULL,
                    avg_fill_price TEXT,
                    reported_at TEXT,
                    error TEXT NOT NULL,
                    raw_response TEXT NOT NULL,
                    PRIMARY KEY (account_id, client_order_id)
                )
                """
            )

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "account_id": row["account_id"],
            "client_order_id": row["client_order_id"],
            "strategy_id": row["strategy_id"],
            "instrument_id": row["instrument_id"],
            "side": row["side"],
            "quantity": Decimal(row["quantity"]),
            "order_type": row["order_type"],
            "limit_price": Decimal(row["limit_price"]) if row["limit_price"] is not None else None,
            "time_in_force": row["time_in_force"],
            "status": row["status"],
            "created_at": datetime.fromisoformat(row["created_at"]),
            "reason": row["reason"],
            "broker_order_id": row["broker_order_id"],
            "filled_quantity": Decimal(row["filled_quantity"]),
            "avg_fill_price": Decimal(row["avg_fill_price"]) if row["avg_fill_price"] is not None else None,
            "reported_at": datetime.fromisoformat(row["reported_at"]) if row["reported_at"] is not None else None,
            "error": row["error"],
            "raw_response": json.loads(row["raw_response"]),
        }
