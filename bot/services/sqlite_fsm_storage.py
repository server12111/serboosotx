"""aiogram FSM storage backed by SQLite — replaces RedisStorage so in-progress dialog
state (order link/quantity, a top-up amount) survives a bot restart without needing a
separate Redis process. Uses its own file, not the main app DB: FSM writes happen on
almost every user tap/keystroke and would otherwise compete for the same
single-writer lock as order/balance writes.

Single aiosqlite connection shared across the app — SQLite serializes writes to one
file regardless of connection count, so a pool would buy nothing here, only added
complexity. WAL + a busy_timeout (set in connect()) let concurrent reads proceed
and make writers wait-and-retry instead of failing outright.
"""
import json
import os
from typing import Any, Mapping

import aiosqlite
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey


def _key_str(key: StorageKey) -> str:
    return ":".join(
        str(part)
        for part in (
            key.bot_id,
            key.chat_id,
            key.user_id,
            key.thread_id,
            key.business_connection_id,
            key.destiny,
        )
    )


class SQLiteStorage(BaseStorage):
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=10000")
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS fsm_state ("
            "key TEXT PRIMARY KEY, state TEXT, data TEXT NOT NULL DEFAULT '{}')"
        )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        state_str = state.state if isinstance(state, State) else state
        await self._conn.execute(
            "INSERT INTO fsm_state (key, state, data) VALUES (?, ?, '{}') "
            "ON CONFLICT(key) DO UPDATE SET state = excluded.state",
            (_key_str(key), state_str),
        )
        await self._conn.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        async with self._conn.execute(
            "SELECT state FROM fsm_state WHERE key = ?", (_key_str(key),)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        await self._conn.execute(
            "INSERT INTO fsm_state (key, state, data) VALUES (?, NULL, ?) "
            "ON CONFLICT(key) DO UPDATE SET data = excluded.data",
            (_key_str(key), json.dumps(dict(data))),
        )
        await self._conn.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with self._conn.execute(
            "SELECT data FROM fsm_state WHERE key = ?", (_key_str(key),)
        ) as cur:
            row = await cur.fetchone()
        return json.loads(row[0]) if row and row[0] else {}
