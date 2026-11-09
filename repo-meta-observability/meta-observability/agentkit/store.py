"""
Small async document store with two interchangeable backends:

* SupabaseStore: PostgREST with the signed-in user's JWT, so row level security applies.
* SqliteStore:   a local file. Used automatically while the Supabase tables have not been created yet
                 (run shared/supabase/0001_init.sql in the Supabase SQL editor), and for offline tests.

Rows are plain dicts. Filters are equality only, which is all the agents need.
"""

import asyncio
import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx

from .settings import get_settings

log = logging.getLogger("agentkit.store")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteStore:
    backend = "sqlite"

    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._known: set = set()

    def _ensure(self, table: str) -> None:
        if table in self._known:
            return
        if not table.replace("_", "").isalnum():
            raise ValueError("bad table name")
        self._conn.execute(
            f'CREATE TABLE IF NOT EXISTS "{table}" (id TEXT PRIMARY KEY, user_id TEXT, created_at TEXT, data TEXT NOT NULL)'
        )
        self._conn.execute(f'CREATE INDEX IF NOT EXISTS "ix_{table}_user" ON "{table}"(user_id, created_at)')
        self._conn.execute(f'CREATE INDEX IF NOT EXISTS "ix_{table}_time" ON "{table}"(created_at)')
        self._known.add(table)

    @staticmethod
    def _col(key: str) -> str:
        if not key.replace("_", "").isalnum():
            raise ValueError("bad column name")
        if key in ("id", "user_id", "created_at"):
            return f'"{key}"'  # real, indexable columns
        return f"json_extract(data, '$.{key}')"

    def _insert(self, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(row)
        row.setdefault("id", uuid.uuid4().hex)
        row.setdefault("created_at", now_iso())
        with self._lock:
            self._ensure(table)
            self._conn.execute(
                f'INSERT OR REPLACE INTO "{table}"(id, user_id, created_at, data) VALUES (?,?,?,?)',
                (str(row["id"]), row.get("user_id"), row["created_at"], json.dumps(row, default=str)),
            )
            self._conn.commit()
        return row

    def _insert_many(self, table: str, rows: List[Dict[str, Any]]) -> int:
        with self._lock:
            self._ensure(table)
            data = []
            for r in rows:
                r = dict(r)
                r.setdefault("id", uuid.uuid4().hex)
                r.setdefault("created_at", now_iso())
                data.append((str(r["id"]), r.get("user_id"), r["created_at"], json.dumps(r, default=str)))
            self._conn.executemany(f'INSERT OR REPLACE INTO "{table}"(id, user_id, created_at, data) VALUES (?,?,?,?)', data)
            self._conn.commit()
        return len(rows)

    def _select(self, table, eq, order, desc, limit) -> List[Dict[str, Any]]:
        with self._lock:
            self._ensure(table)
            where, args = [], []
            for k, v in (eq or {}).items():
                where.append(f"{self._col(k)} IS ?" if v is None else f"{self._col(k)} = ?")
                args.append(v)
            sql = f'SELECT data FROM "{table}"'
            if where:
                sql += " WHERE " + " AND ".join(where)
            if order:
                sql += f" ORDER BY {self._col(order)} {'DESC' if desc else 'ASC'}"
            sql += " LIMIT ?"
            args.append(int(limit))
            raw = self._conn.execute(sql, args).fetchall()
        return [json.loads(r[0]) for r in raw]  # parse outside the lock so readers do not stall writers

    def _update(self, table, eq, patch) -> List[Dict[str, Any]]:
        rows = self._select(table, eq, None, True, 1000)
        out = []
        for r in rows:
            r.update(patch)
            r["updated_at"] = now_iso()
            self._insert(table, r)
            out.append(r)
        return out

    def _delete(self, table, eq) -> int:
        rows = self._select(table, eq, None, True, 1000)
        with self._lock:
            for r in rows:
                self._conn.execute(f'DELETE FROM "{table}" WHERE id = ?', (str(r["id"]),))
            self._conn.commit()
        return len(rows)

    async def insert(self, table, row, token=None):
        return await asyncio.to_thread(self._insert, table, row)

    async def insert_many(self, table, rows, token=None):
        return await asyncio.to_thread(self._insert_many, table, rows)

    async def select(self, table, eq=None, order="created_at", desc=True, limit=100, token=None):
        return await asyncio.to_thread(self._select, table, eq, order, desc, limit)

    async def update(self, table, eq, patch, token=None):
        return await asyncio.to_thread(self._update, table, eq, patch)

    async def delete(self, table, eq, token=None):
        return await asyncio.to_thread(self._delete, table, eq)

    def describe(self) -> Dict[str, Any]:
        return {"backend": "sqlite", "path": self.path}


class SupabaseStore:
    backend = "supabase"

    def __init__(self, url: str, key: str) -> None:
        self.url, self.key = url.rstrip("/"), key
        self._c = httpx.AsyncClient(timeout=15, limits=httpx.Limits(max_connections=100))

    def _h(self, token: Optional[str], prefer: Optional[str] = None) -> Dict[str, str]:
        h = {"apikey": self.key, "Authorization": f"Bearer {token or self.key}", "Content-Type": "application/json"}
        if prefer:
            h["Prefer"] = prefer
        return h

    @staticmethod
    def _filters(eq: Optional[Dict[str, Any]]) -> Dict[str, str]:
        return {k: ("is.null" if v is None else f"eq.{v}") for k, v in (eq or {}).items()}

    async def _check(self, r: httpx.Response):
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase {r.status_code}: {r.text[:200]}")
        return r.json() if r.text else []

    async def insert(self, table, row, token=None):
        row = dict(row)
        row.setdefault("id", str(uuid.uuid4())) if table not in _BIGINT_ID_TABLES else None
        r = await self._c.post(f"{self.url}/rest/v1/{table}", headers=self._h(token, "return=representation"), json=row)
        data = await self._check(r)
        return data[0] if data else row

    async def insert_many(self, table, rows, token=None):
        rows = [dict(r) for r in rows]
        if table not in _BIGINT_ID_TABLES:
            for r in rows:
                r.setdefault("id", str(uuid.uuid4()))
        r = await self._c.post(f"{self.url}/rest/v1/{table}", headers=self._h(token), json=rows)
        await self._check(r)
        return len(rows)

    async def select(self, table, eq=None, order="created_at", desc=True, limit=100, token=None):
        params = {**self._filters(eq), "limit": str(limit)}
        if order:
            params["order"] = f"{order}.{'desc' if desc else 'asc'}"
        r = await self._c.get(f"{self.url}/rest/v1/{table}", headers=self._h(token), params=params)
        return await self._check(r)

    async def update(self, table, eq, patch, token=None):
        r = await self._c.patch(
            f"{self.url}/rest/v1/{table}", headers=self._h(token, "return=representation"),
            params=self._filters(eq), json={**patch, "updated_at": now_iso()},
        )
        return await self._check(r)

    async def delete(self, table, eq, token=None):
        r = await self._c.delete(f"{self.url}/rest/v1/{table}", headers=self._h(token, "return=representation"), params=self._filters(eq))
        return len(await self._check(r))

    def describe(self) -> Dict[str, Any]:
        return {"backend": "supabase", "url": self.url}


_BIGINT_ID_TABLES = {"llm_calls", "service_metrics"}  # tables whose primary key is generated by the database

_store = None
_lock = asyncio.Lock()


async def _tables_exist(url: str, key: str, tables: Iterable[str]) -> List[str]:
    missing = []
    async with httpx.AsyncClient(timeout=10) as c:
        for t in tables:
            try:
                r = await c.get(f"{url}/rest/v1/{t}", params={"limit": "0"}, headers={"apikey": key, "Authorization": f"Bearer {key}"})
                if r.status_code == 404 or "PGRST205" in r.text:
                    missing.append(t)
            except httpx.HTTPError:
                missing.append(t)
    return missing


async def get_store(required_tables: Iterable[str] = ()) -> Any:
    """Picks Supabase when every required table exists, otherwise falls back to SQLite and says why."""
    global _store
    if _store is not None:
        return _store
    async with _lock:
        if _store is not None:
            return _store
        s = get_settings()
        want = s.store_backend
        if want in ("auto", "supabase") and s.supabase_url and s.supabase_publishable_key:
            missing = await _tables_exist(s.supabase_url, s.supabase_publishable_key, list(required_tables))
            if not missing:
                _store = SupabaseStore(s.supabase_url, s.supabase_publishable_key)
                log.info("store: supabase")
                return _store
            msg = f"Supabase tables missing {missing}; run shared/supabase/0001_init.sql in the Supabase SQL editor"
            if want == "supabase":
                raise RuntimeError(msg)
            log.warning("store: %s. Using local SQLite meanwhile.", msg)
        _store = SqliteStore(s.sqlite_path)
        return _store


def reset_store_for_tests() -> None:
    global _store
    _store = None
