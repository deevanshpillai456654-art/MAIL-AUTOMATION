"""
PluginRepository — tenant-scoped, sandbox-enforced data access for plugins.

Wraps DBAdapter with a fluent query builder so plugins never write raw SQL.
All queries are automatically scoped to the plugin's tenant_id.

Usage::

    repo = PluginRepository(db_adapter, entity="contacts")
    contacts = repo.filter(email="alice@example.com").all()
    repo.insert({"name": "Alice", "email": "alice@example.com"})
    repo.update(id=1, data={"name": "Alicia"})
    repo.delete(id=1)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _require_identifier(value: str, *, label: str = "identifier") -> str:
    text = str(value or "")
    if not _IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"Unsafe SQL {label}: {text!r}")
    return text


class QueryBuilder:
    """Minimal fluent query builder — NOT a full ORM."""

    def __init__(self, repo: "PluginRepository") -> None:
        self._repo    = repo
        self._filters: Dict[str, Any] = {}
        self._limit:   Optional[int]  = None
        self._offset:  int            = 0
        self._order_by: Optional[str] = None

    def filter(self, **kwargs: Any) -> "QueryBuilder":
        self._filters.update(kwargs)
        return self

    def limit(self, n: int) -> "QueryBuilder":
        self._limit = max(0, int(n))
        return self

    def offset(self, n: int) -> "QueryBuilder":
        self._offset = max(0, int(n))
        return self

    def order_by(self, column: str) -> "QueryBuilder":
        self._order_by = _require_identifier(column, label="order column")
        return self

    def all(self) -> List[Dict[str, Any]]:
        return self._repo._execute_query(
            self._filters, limit=self._limit, offset=self._offset, order_by=self._order_by
        )

    def first(self) -> Optional[Dict[str, Any]]:
        results = self.limit(1).all()
        return results[0] if results else None

    def count(self) -> int:
        return self._repo._execute_count(self._filters)


class PluginRepository:
    """
    Plugin-safe repository for a single entity table.

    The table name is derived from entity and must be in the sandbox's
    allowed_db_tables list to proceed.
    """

    def __init__(
        self,
        db:        Any,
        *,
        entity:    str,
        plugin_id: str,
        tenant_id: str,
        sandbox:   Optional[Any] = None,
    ) -> None:
        self._db        = db
        self._entity    = entity
        self._table     = _require_identifier(entity.rstrip("s") + "s", label="table")   # simple pluralise; override if needed
        self._plugin_id = plugin_id
        self._tenant_id = tenant_id
        self._sandbox   = sandbox

    # ── Public API ────────────────────────────────────────────────────────

    def filter(self, **kwargs: Any) -> QueryBuilder:
        return QueryBuilder(self).filter(**kwargs)

    def get_by_id(self, record_id: Any) -> Optional[Dict[str, Any]]:
        return self.filter(id=record_id).first()

    def all(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.filter().limit(limit).all()

    def insert(self, data: Dict[str, Any]) -> Optional[str]:
        self._check_write()
        data = {**data, "tenant_id": self._tenant_id}
        for key in data:
            _require_identifier(key, label="column")
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" * len(data))
        self._db.execute(
            f"INSERT OR IGNORE INTO {self._table} ({cols}) VALUES ({placeholders})",  # nosec B608
            tuple(data.values()),
        )
        return data.get("id")

    def update(self, record_id: Any, data: Dict[str, Any]) -> None:
        self._check_write()
        if not data:
            return
        for key in data:
            _require_identifier(key, label="column")
        sets = ", ".join(f"{k}=?" for k in data)
        self._db.execute(
            f"UPDATE {self._table} SET {sets} WHERE id=? AND tenant_id=?",  # nosec B608
            (*data.values(), record_id, self._tenant_id),
        )

    def delete(self, record_id: Any) -> None:
        self._check_write()
        self._db.execute(
            f"DELETE FROM {self._table} WHERE id=? AND tenant_id=?",  # nosec B608
            (record_id, self._tenant_id),
        )

    # ── Internal ──────────────────────────────────────────────────────────

    def _check_write(self) -> None:
        if self._sandbox:
            self._sandbox.assert_can_access_table(self._plugin_id, self._table, write=True)

    def _execute_query(
        self,
        filters: Dict[str, Any],
        *,
        limit:    Optional[int],
        offset:   int,
        order_by: Optional[str],
    ) -> List[Dict[str, Any]]:
        if self._sandbox:
            self._sandbox.assert_can_access_table(self._plugin_id, self._table, write=False)

        where, params = self._build_where(filters)
        sql = f"SELECT * FROM {self._table}{where}"  # nosec B608
        if order_by:
            sql += f" ORDER BY {order_by}"
        params = list(params)
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])
        rows = self._db.fetch_all(sql, params) or []
        return [dict(r) for r in rows]

    def _execute_count(self, filters: Dict[str, Any]) -> int:
        where, params = self._build_where(filters)
        row = self._db.fetch_one(
            f"SELECT COUNT(*) AS n FROM {self._table}{where}", params  # nosec B608
        )
        return row["n"] if row else 0

    def _build_where(self, filters: Dict[str, Any]) -> tuple:
        conditions: List[str] = ["tenant_id=?"]
        params: List[Any]     = [self._tenant_id]
        for k, v in filters.items():
            _require_identifier(k, label="filter column")
            conditions.append(f"{k}=?")
            params.append(v)
        return f" WHERE {' AND '.join(conditions)}", tuple(params)
