from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from backtest.data.metadata import MetadataStore


class InstrumentTagRef(BaseModel):
    tag_id: str
    name: str
    color: str | None = None


class InstrumentRecord(BaseModel):
    instrument_id: str
    symbol: str | None = None
    name: str | None = None
    market: str | None = None
    exchange: str | None = None
    asset_class: str | None = None
    quote_currency: str | None = None
    source_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[InstrumentTagRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class InstrumentPage(BaseModel):
    instruments: list[InstrumentRecord]
    total: int
    limit: int
    offset: int


class InstrumentUpsertResult(BaseModel):
    action: str
    record: InstrumentRecord


class InstrumentTagRecord(BaseModel):
    tag_id: str
    name: str
    description: str | None = None
    color: str | None = None
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class InstrumentTagMembership(BaseModel):
    tag_id: str
    instrument_id: str
    created_at: datetime


class InstrumentTagMembers(BaseModel):
    tag: InstrumentTagRecord
    members: list[InstrumentTagMembership]


class InstrumentCreate(BaseModel):
    instrument_id: str
    symbol: str | None = None
    name: str | None = None
    market: str | None = None
    exchange: str | None = None
    asset_class: str | None = None
    quote_currency: str | None = None
    source_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("instrument_id")
    @classmethod
    def normalize_instrument_id(cls, value: str) -> str:
        return _normalize_instrument_id(value)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_instrument_id(value)

    @field_validator("quote_currency")
    @classmethod
    def normalize_quote_currency(cls, value: str | None) -> str | None:
        return _clean_optional_text(value, upper=True)

    @field_validator("name", "market", "exchange", "asset_class", "source_id")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @model_validator(mode="after")
    def default_symbol(self) -> InstrumentCreate:
        if self.symbol is None:
            self.symbol = self.instrument_id
        return self


class InstrumentPatch(BaseModel):
    symbol: str | None = None
    name: str | None = None
    market: str | None = None
    exchange: str | None = None
    asset_class: str | None = None
    quote_currency: str | None = None
    source_id: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_instrument_id(value)

    @field_validator("quote_currency")
    @classmethod
    def normalize_quote_currency(cls, value: str | None) -> str | None:
        return _clean_optional_text(value, upper=True)

    @field_validator("name", "market", "exchange", "asset_class", "source_id")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


class InstrumentTagCreate(BaseModel):
    tag_id: str | None = None
    name: str
    description: str | None = None
    color: str | None = None

    @field_validator("tag_id")
    @classmethod
    def normalize_tag_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_tag_id(value)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tag name must not be empty")
        return normalized

    @field_validator("description", "color")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @model_validator(mode="after")
    def default_tag_id(self) -> InstrumentTagCreate:
        if self.tag_id is None:
            self.tag_id = _normalize_tag_id(self.name)
        return self


class InstrumentTagPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("tag name must not be empty")
        return normalized

    @field_validator("description", "color")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


class InstrumentStore:
    def __init__(self, metadata: MetadataStore) -> None:
        self.metadata = metadata

    def create_instrument(self, payload: dict[str, Any]) -> InstrumentRecord:
        data = InstrumentCreate.model_validate(payload)
        now = self.metadata.now().isoformat()
        try:
            with self.metadata.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO instruments
                    (
                        instrument_id, symbol, name, market, exchange, asset_class,
                        quote_currency, source_id, metadata_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data.instrument_id,
                        data.symbol,
                        data.name,
                        data.market,
                        data.exchange,
                        data.asset_class,
                        data.quote_currency,
                        data.source_id,
                        _encode_metadata(data.metadata),
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Instrument already exists: {data.instrument_id}") from exc
        return self.get_instrument(data.instrument_id)

    def upsert_instrument(self, payload: dict[str, Any], *, touch: bool = False) -> InstrumentUpsertResult:
        data = InstrumentCreate.model_validate(payload)
        try:
            existing = self.get_instrument(data.instrument_id)
        except ValueError as exc:
            if not _is_unknown_instrument_error(exc, data.instrument_id):
                raise
            return InstrumentUpsertResult(
                action="created",
                record=self.create_instrument(data.model_dump()),
            )

        compare_fields = (
            "symbol",
            "name",
            "market",
            "exchange",
            "asset_class",
            "quote_currency",
            "source_id",
            "metadata",
        )
        explicit_fields = set(payload) & set(compare_fields)
        updates = {
            field_name: getattr(data, field_name)
            for field_name in explicit_fields
            if getattr(existing, field_name) != getattr(data, field_name)
        }
        if not updates:
            if touch:
                return InstrumentUpsertResult(
                    action="unchanged",
                    record=self.touch_instrument(data.instrument_id),
                )
            return InstrumentUpsertResult(action="unchanged", record=existing)

        return InstrumentUpsertResult(
            action="updated",
            record=self.update_instrument(data.instrument_id, updates),
        )

    def touch_instrument(self, instrument_id: str) -> InstrumentRecord:
        normalized = _normalize_instrument_id(instrument_id)
        self.get_instrument(normalized)
        with self.metadata.connect() as conn:
            conn.execute(
                "UPDATE instruments SET updated_at = ? WHERE instrument_id = ?",
                (self.metadata.now().isoformat(), normalized),
            )
        return self.get_instrument(normalized)

    def get_instrument(self, instrument_id: str) -> InstrumentRecord:
        normalized = _normalize_instrument_id(instrument_id)
        with self.metadata.connect() as conn:
            row = conn.execute(
                "SELECT * FROM instruments WHERE instrument_id = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown instrument: {normalized}")
            tags = self._tags_for_instruments(conn, [normalized]).get(normalized, [])
        return self._record_from_row(row, tags)

    def update_instrument(self, instrument_id: str, payload: dict[str, Any]) -> InstrumentRecord:
        normalized = _normalize_instrument_id(instrument_id)
        self.get_instrument(normalized)
        data = InstrumentPatch.model_validate(payload)
        updates = data.model_dump(exclude_unset=True)
        if not updates:
            return self.get_instrument(normalized)

        values: list[Any] = []
        assignments: list[str] = []
        column_by_field = {
            "symbol": "symbol",
            "name": "name",
            "market": "market",
            "exchange": "exchange",
            "asset_class": "asset_class",
            "quote_currency": "quote_currency",
            "source_id": "source_id",
            "metadata": "metadata_json",
        }
        for field_name, value in updates.items():
            column_name = column_by_field[field_name]
            assignments.append(f"{column_name} = ?")
            values.append(_encode_metadata(value) if field_name == "metadata" else value)

        assignments.append("updated_at = ?")
        values.append(self.metadata.now().isoformat())
        values.append(normalized)

        with self.metadata.connect() as conn:
            conn.execute(
                f"""
                UPDATE instruments
                SET {", ".join(assignments)}
                WHERE instrument_id = ?
                """,
                values,
            )
        return self.get_instrument(normalized)

    def delete_instrument(self, instrument_id: str) -> None:
        normalized = _normalize_instrument_id(instrument_id)
        self.get_instrument(normalized)
        with self.metadata.connect() as conn:
            conn.execute("DELETE FROM instruments WHERE instrument_id = ?", (normalized,))

    def symbol_names(self, *, source_id: str | None = None) -> dict[str, str]:
        """Return symbol -> display name from the instrument inventory.

        This is the canonical source for Chinese/English instrument names used by
        K-line search. Names are not read from universe CSV metadata.
        """
        where = ""
        params: list[Any] = []
        if source_id is not None and source_id.strip():
            where = "WHERE source_id = ?"
            params.append(source_id.strip())
        with self.metadata.connect() as conn:
            rows = conn.execute(
                f"SELECT symbol, name FROM instruments {where}",
                params,
            ).fetchall()
        names: dict[str, str] = {}
        for row in rows:
            symbol = str(row["symbol"] or "").strip()
            if not symbol:
                continue
            name = str(row["name"] or "").strip()
            existing = names.get(symbol, "")
            if symbol not in names or (name and not existing):
                names[symbol] = name
        return names

    def list_instruments(
        self,
        *,
        source_id: str | None = None,
        q: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> InstrumentPage:
        limit, offset = _normalize_pagination(limit, offset)
        joins = ""
        where: list[str] = []
        params: list[Any] = []

        if tag is not None and tag.strip():
            joins = """
                JOIN instrument_tag_members tm ON tm.instrument_id = i.instrument_id
                JOIN instrument_tags t ON t.tag_id = tm.tag_id
            """
            where.append("(t.tag_id = ? OR t.name = ?)")
            params.extend([tag.strip(), tag.strip()])
        if source_id is not None and source_id.strip():
            where.append("i.source_id = ?")
            params.append(source_id.strip())
        if q is not None and q.strip():
            pattern = f"%{q.strip()}%"
            where.append(
                """
                (
                    i.instrument_id LIKE ?
                    OR i.symbol LIKE ?
                    OR i.name LIKE ?
                    OR i.exchange LIKE ?
                )
                """
            )
            params.extend([pattern, pattern, pattern, pattern])

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self.metadata.connect() as conn:
            total = conn.execute(
                f"""
                SELECT COUNT(DISTINCT i.instrument_id)
                FROM instruments i
                {joins}
                {where_clause}
                """,
                params,
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT DISTINCT i.*
                FROM instruments i
                {joins}
                {where_clause}
                ORDER BY i.updated_at DESC, i.instrument_id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
            tags_by_instrument = self._tags_for_instruments(
                conn,
                [row["instrument_id"] for row in rows],
            )

        return InstrumentPage(
            instruments=[
                self._record_from_row(row, tags_by_instrument.get(row["instrument_id"], []))
                for row in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    def create_tag(self, payload: dict[str, Any]) -> InstrumentTagRecord:
        data = InstrumentTagCreate.model_validate(payload)
        now = self.metadata.now().isoformat()
        try:
            with self.metadata.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO instrument_tags
                    (tag_id, name, description, color, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data.tag_id,
                        data.name,
                        data.description,
                        data.color,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Tag already exists: {data.tag_id}") from exc
        return self.get_tag(data.tag_id)

    def ensure_tag(self, payload: dict[str, Any]) -> InstrumentTagRecord:
        data = InstrumentTagCreate.model_validate(payload)
        try:
            return self.get_tag(data.tag_id)
        except ValueError as exc:
            if not _is_unknown_tag_error(exc, data.tag_id):
                raise
            return self.create_tag(data.model_dump())

    def get_tag(self, tag_id: str) -> InstrumentTagRecord:
        normalized = _normalize_tag_id(tag_id)
        with self.metadata.connect() as conn:
            row = conn.execute(
                """
                SELECT t.*, COUNT(tm.instrument_id) AS member_count
                FROM instrument_tags t
                LEFT JOIN instrument_tag_members tm ON tm.tag_id = t.tag_id
                WHERE t.tag_id = ?
                GROUP BY t.tag_id
                """,
                (normalized,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown tag: {normalized}")
        return self._tag_from_row(row)

    def list_tags(self) -> list[InstrumentTagRecord]:
        with self.metadata.connect() as conn:
            rows = conn.execute(
                """
                SELECT t.*, COUNT(tm.instrument_id) AS member_count
                FROM instrument_tags t
                LEFT JOIN instrument_tag_members tm ON tm.tag_id = t.tag_id
                GROUP BY t.tag_id
                ORDER BY t.name, t.tag_id
                """
            ).fetchall()
        return [self._tag_from_row(row) for row in rows]

    def update_tag(self, tag_id: str, payload: dict[str, Any]) -> InstrumentTagRecord:
        normalized = _normalize_tag_id(tag_id)
        self.get_tag(normalized)
        data = InstrumentTagPatch.model_validate(payload)
        updates = data.model_dump(exclude_unset=True)
        if not updates:
            return self.get_tag(normalized)

        assignments: list[str] = []
        values: list[Any] = []
        for field_name, value in updates.items():
            assignments.append(f"{field_name} = ?")
            values.append(value)
        assignments.append("updated_at = ?")
        values.append(self.metadata.now().isoformat())
        values.append(normalized)

        try:
            with self.metadata.connect() as conn:
                conn.execute(
                    f"""
                    UPDATE instrument_tags
                    SET {", ".join(assignments)}
                    WHERE tag_id = ?
                    """,
                    values,
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Tag already exists with name: {updates.get('name')}") from exc
        return self.get_tag(normalized)

    def delete_tag(self, tag_id: str) -> None:
        normalized = _normalize_tag_id(tag_id)
        self.get_tag(normalized)
        with self.metadata.connect() as conn:
            conn.execute("DELETE FROM instrument_tags WHERE tag_id = ?", (normalized,))

    def replace_tag_members(
        self,
        tag_id: str,
        instrument_ids: list[str],
    ) -> InstrumentTagMembers:
        normalized_tag = _normalize_tag_id(tag_id)
        normalized_ids = _normalize_instrument_ids(instrument_ids)
        self.get_tag(normalized_tag)
        self._ensure_instruments_exist(normalized_ids)
        now = self.metadata.now().isoformat()
        with self.metadata.connect() as conn:
            conn.execute(
                "DELETE FROM instrument_tag_members WHERE tag_id = ?",
                (normalized_tag,),
            )
            conn.executemany(
                """
                INSERT INTO instrument_tag_members (tag_id, instrument_id, created_at)
                VALUES (?, ?, ?)
                """,
                [(normalized_tag, instrument_id, now) for instrument_id in normalized_ids],
            )
        return self.tag_members(normalized_tag)

    def add_tag_members(
        self,
        tag_id: str,
        instrument_ids: list[str],
    ) -> InstrumentTagMembers:
        normalized_tag = _normalize_tag_id(tag_id)
        normalized_ids = _normalize_instrument_ids(instrument_ids)
        self.get_tag(normalized_tag)
        self._ensure_instruments_exist(normalized_ids)
        now = self.metadata.now().isoformat()
        with self.metadata.connect() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO instrument_tag_members (tag_id, instrument_id, created_at)
                VALUES (?, ?, ?)
                """,
                [(normalized_tag, instrument_id, now) for instrument_id in normalized_ids],
            )
        return self.tag_members(normalized_tag)

    def remove_tag_member(
        self,
        tag_id: str,
        instrument_id: str,
    ) -> InstrumentTagMembers:
        normalized_tag = _normalize_tag_id(tag_id)
        normalized_instrument = _normalize_instrument_id(instrument_id)
        self.get_tag(normalized_tag)
        with self.metadata.connect() as conn:
            conn.execute(
                """
                DELETE FROM instrument_tag_members
                WHERE tag_id = ? AND instrument_id = ?
                """,
                (normalized_tag, normalized_instrument),
            )
        return self.tag_members(normalized_tag)

    def tag_members(self, tag_id: str) -> InstrumentTagMembers:
        normalized = _normalize_tag_id(tag_id)
        tag = self.get_tag(normalized)
        with self.metadata.connect() as conn:
            rows = conn.execute(
                """
                SELECT tag_id, instrument_id, created_at
                FROM instrument_tag_members
                WHERE tag_id = ?
                ORDER BY created_at, instrument_id
                """,
                (normalized,),
            ).fetchall()
        return InstrumentTagMembers(
            tag=tag,
            members=[
                InstrumentTagMembership(
                    tag_id=row["tag_id"],
                    instrument_id=row["instrument_id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ],
        )

    def _ensure_instruments_exist(self, instrument_ids: list[str]) -> None:
        if not instrument_ids:
            return
        placeholders = ", ".join("?" for _ in instrument_ids)
        with self.metadata.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT instrument_id
                FROM instruments
                WHERE instrument_id IN ({placeholders})
                """,
                instrument_ids,
            ).fetchall()
        existing = {row["instrument_id"] for row in rows}
        missing = [instrument_id for instrument_id in instrument_ids if instrument_id not in existing]
        if missing:
            raise ValueError(f"Unknown instrument: {missing[0]}")

    def _tags_for_instruments(
        self,
        conn: sqlite3.Connection,
        instrument_ids: list[str],
    ) -> dict[str, list[InstrumentTagRef]]:
        if not instrument_ids:
            return {}
        placeholders = ", ".join("?" for _ in instrument_ids)
        rows = conn.execute(
            f"""
            SELECT tm.instrument_id, t.tag_id, t.name, t.color
            FROM instrument_tag_members tm
            JOIN instrument_tags t ON t.tag_id = tm.tag_id
            WHERE tm.instrument_id IN ({placeholders})
            ORDER BY t.name, t.tag_id
            """,
            instrument_ids,
        ).fetchall()
        result = {instrument_id: [] for instrument_id in instrument_ids}
        for row in rows:
            result[row["instrument_id"]].append(
                InstrumentTagRef(
                    tag_id=row["tag_id"],
                    name=row["name"],
                    color=row["color"],
                )
            )
        return result

    def _tag_from_row(self, row: sqlite3.Row) -> InstrumentTagRecord:
        return InstrumentTagRecord(
            tag_id=row["tag_id"],
            name=row["name"],
            description=row["description"],
            color=row["color"],
            member_count=row["member_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _record_from_row(
        self,
        row: sqlite3.Row,
        tags: list[InstrumentTagRef],
    ) -> InstrumentRecord:
        return InstrumentRecord(
            instrument_id=row["instrument_id"],
            symbol=row["symbol"],
            name=row["name"],
            market=row["market"],
            exchange=row["exchange"],
            asset_class=row["asset_class"],
            quote_currency=row["quote_currency"],
            source_id=row["source_id"],
            metadata=_decode_metadata(row["metadata_json"]),
            tags=tags,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


def _normalize_instrument_id(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError("instrument_id must not be empty")
    return normalized


def _normalize_instrument_ids(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_instrument_id(value)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _normalize_tag_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("tag_id must not be empty")
    return normalized


def _clean_optional_text(value: str | None, *, upper: bool = False) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized.upper() if upper else normalized


def _encode_metadata(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _decode_metadata(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    decoded = json.loads(value)
    return decoded if isinstance(decoded, dict) else {}


def _normalize_pagination(limit: int, offset: int) -> tuple[int, int]:
    if limit < 1:
        raise ValueError("limit must be greater than or equal to 1")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0")
    return min(limit, 500), offset


def _is_unknown_instrument_error(exc: ValueError, instrument_id: str) -> bool:
    return str(exc) == f"Unknown instrument: {instrument_id}"


def _is_unknown_tag_error(exc: ValueError, tag_id: str) -> bool:
    return str(exc) == f"Unknown tag: {tag_id}"
