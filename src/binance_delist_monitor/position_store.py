from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .trade_models import Pool, PositionRecord, SignalContext


class PositionStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pools (
                    pool_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    announcement_key TEXT,
                    allocated_capital REAL NOT NULL,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    signal_id TEXT PRIMARY KEY,
                    announcement_id TEXT NOT NULL,
                    announcement_title TEXT NOT NULL,
                    announcement_url TEXT NOT NULL,
                    announcement_publish_time TEXT NOT NULL,
                    matched_keywords TEXT NOT NULL,
                    matched_symbols TEXT NOT NULL,
                    triggered_at TEXT NOT NULL,
                    pool_id TEXT,
                    pool_capital REAL NOT NULL,
                    symbol_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    position_id TEXT PRIMARY KEY,
                    trade_id TEXT NOT NULL,
                    signal_id TEXT NOT NULL,
                    announcement_id TEXT NOT NULL,
                    announcement_title TEXT NOT NULL,
                    announcement_url TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    pool_id TEXT NOT NULL,
                    allocated_capital REAL NOT NULL,
                    leverage INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    status TEXT NOT NULL,
                    open_time TEXT NOT NULL,
                    exchange_delivery_time_ms INTEGER,
                    close_time TEXT,
                    close_price REAL,
                    close_reason TEXT,
                    pnl REAL NOT NULL DEFAULT 0,
                    pnl_pct REAL NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lifecycle (
                    announcement_id TEXT PRIMARY KEY,
                    announcement_title TEXT NOT NULL,
                    pool_id TEXT NOT NULL,
                    total_positions INTEGER NOT NULL,
                    open_positions INTEGER NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0,
                    released_capital REAL NOT NULL DEFAULT 0,
                    total_realized_pnl REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        self._ensure_column("positions", "close_price", "REAL")
        self._ensure_column("positions", "exchange_delivery_time_ms", "INTEGER")

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        with self._connect() as conn:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            if any(str(row["name"]).lower() == column.lower() for row in rows):
                return
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def seed_pools(self, pools: Iterable[Pool]) -> None:
        with self._connect() as conn:
            for pool in pools:
                conn.execute(
                    """
                    INSERT INTO pools(pool_id, status, announcement_key, allocated_capital, created_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(pool_id) DO NOTHING
                    """,
                    (
                        pool.pool_id,
                        pool.status,
                        pool.announcement_key,
                        pool.allocated_capital,
                        pool.created_at,
                        pool.updated_at,
                    ),
                )

    def upsert_signal(self, signal: SignalContext) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO signals(
                    signal_id, announcement_id, announcement_title, announcement_url,
                    announcement_publish_time, matched_keywords, matched_symbols,
                    triggered_at, pool_id, pool_capital, symbol_count, status, notes
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    status=excluded.status,
                    notes=excluded.notes,
                    pool_id=excluded.pool_id,
                    pool_capital=excluded.pool_capital,
                    symbol_count=excluded.symbol_count
                """,
                (
                    signal.signal_id,
                    signal.announcement_id,
                    signal.announcement_title,
                    signal.announcement_url,
                    signal.announcement_publish_time,
                    json.dumps(signal.matched_keywords, ensure_ascii=False),
                    json.dumps(signal.matched_symbols, ensure_ascii=False),
                    signal.triggered_at,
                    signal.pool_id,
                    signal.pool_capital,
                    signal.symbol_count,
                    signal.status,
                    json.dumps(signal.notes, ensure_ascii=False),
                ),
            )

    def insert_position(self, position: PositionRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO positions(
                    position_id, trade_id, signal_id, announcement_id, announcement_title, announcement_url,
                    symbol, side, pool_id, allocated_capital, leverage, entry_price, quantity,
                    status, open_time, exchange_delivery_time_ms, close_time, close_price, close_reason, pnl, pnl_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position.position_id,
                    position.trade_id,
                    position.signal_id,
                    position.announcement_id,
                    position.announcement_title,
                    position.announcement_url,
                    position.symbol,
                    position.side,
                    position.pool_id,
                    position.allocated_capital,
                    position.leverage,
                    position.entry_price,
                    position.quantity,
                    position.status,
                    position.open_time,
                    position.exchange_delivery_time_ms,
                    position.close_time,
                    position.close_price,
                    position.close_reason,
                    position.pnl,
                    position.pnl_pct,
                ),
            )

    def update_position(self, position_id: str, **fields) -> None:
        if not fields:
            return
        columns = ", ".join(f"{key}=?" for key in fields.keys())
        params = list(fields.values()) + [position_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE positions SET {columns} WHERE position_id=?", params)

    def get_position(self, position_id: str) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM positions WHERE position_id=?", (position_id,)).fetchone()
            return dict(row) if row else None

    def list_positions(self, status: Optional[str] = None) -> List[Dict[str, object]]:
        query = "SELECT * FROM positions"
        params: List[object] = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY open_time ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def list_open_positions(self) -> List[Dict[str, object]]:
        return self.list_positions(status="OPEN")

    def get_pools(self) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM pools ORDER BY pool_id ASC").fetchall()
            return [dict(row) for row in rows]

    def get_pool(self, pool_id: str) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM pools WHERE pool_id=?", (pool_id,)).fetchone()
            return dict(row) if row else None

    def update_pool(self, pool_id: str, **fields) -> None:
        if not fields:
            return
        columns = ", ".join(f"{key}=?" for key in fields.keys())
        params = list(fields.values()) + [pool_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE pools SET {columns} WHERE pool_id=?", params)

    def list_open_positions_by_signal(self, signal_id: str) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE signal_id=? AND status='OPEN' ORDER BY open_time ASC",
                (signal_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_open_positions_by_pool(self, pool_id: str) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE pool_id=? AND status='OPEN' ORDER BY open_time ASC",
                (pool_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def has_open_positions(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM positions WHERE status='OPEN' LIMIT 1").fetchone()
            return row is not None

    def has_open_positions_for_pool(self, pool_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM positions WHERE pool_id=? AND status='OPEN' LIMIT 1", (pool_id,)).fetchone()
            return row is not None

    def get_signal(self, signal_id: str) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM signals WHERE signal_id=?", (signal_id,)).fetchone()
            return dict(row) if row else None

    def get_last_assigned_pool_id(self) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT pool_id FROM signals WHERE pool_id IS NOT NULL ORDER BY triggered_at DESC LIMIT 1"
            ).fetchone()
            return row["pool_id"] if row else None

    def update_signal(self, signal_id: str, **fields) -> None:
        if not fields:
            return
        columns = ", ".join(f"{key}=?" for key in fields.keys())
        params = list(fields.values()) + [signal_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE signals SET {columns} WHERE signal_id=?", params)

    def get_lifecycle(self, announcement_id: str) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM lifecycle WHERE announcement_id=?", (announcement_id,)).fetchone()
            return dict(row) if row else None

    def list_active_lifecycles(self) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM lifecycle WHERE completed=0 ORDER BY created_at ASC").fetchall()
            return [dict(row) for row in rows]

    def upsert_lifecycle(
        self,
        announcement_id: str,
        announcement_title: str,
        pool_id: str,
        total_positions: int,
        open_positions: int,
        completed: bool = False,
        released_capital: float = 0.0,
        total_realized_pnl: float = 0.0,
    ) -> None:
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO lifecycle(
                    announcement_id, announcement_title, pool_id, total_positions, open_positions,
                    completed, released_capital, total_realized_pnl, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(announcement_id) DO UPDATE SET
                    announcement_title=excluded.announcement_title,
                    pool_id=excluded.pool_id,
                    total_positions=excluded.total_positions,
                    open_positions=excluded.open_positions,
                    completed=excluded.completed,
                    released_capital=excluded.released_capital,
                    total_realized_pnl=excluded.total_realized_pnl,
                    updated_at=excluded.updated_at
                """,
                (
                    announcement_id,
                    announcement_title,
                    pool_id,
                    total_positions,
                    open_positions,
                    1 if completed else 0,
                    released_capital,
                    total_realized_pnl,
                    now,
                    now,
                ),
            )

    def update_lifecycle(self, announcement_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = datetime.utcnow().isoformat()
        columns = ", ".join(f"{key}=?" for key in fields.keys())
        params = list(fields.values()) + [announcement_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE lifecycle SET {columns} WHERE announcement_id=?", params)
