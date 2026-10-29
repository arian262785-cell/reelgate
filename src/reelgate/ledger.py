"""SQLite SHA-256 asset ledger for media file and source clip deduplication."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any

from .inspector import compute_file_sha256


class DuplicateAssetError(RuntimeError):
    """Raised when a master media file or source clip hash already exists in the ledger."""


class AssetLedger:
    """Persistent SQLite ledger tracking SHA-256 hashes of published videos and source clips."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS registered_assets (
                    sha256 TEXT PRIMARY KEY,
                    asset_role TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    channel_tag TEXT NOT NULL,
                    registered_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def has_hash(self, sha256_hex: str) -> bool:
        """Return True if the given SHA-256 digest is already recorded in the ledger."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM registered_assets WHERE sha256 = ?",
                (sha256_hex.lower(),),
            ).fetchone()
            return row is not None

    def register_file(
        self,
        file_path: str | Path,
        asset_role: str = "master",
        channel_tag: str = "default",
    ) -> dict[str, Any]:
        """Compute SHA-256 of file_path and insert it into the ledger, raising on duplicates."""
        path = Path(file_path)
        digest = compute_file_sha256(path)
        if self.has_hash(digest):
            raise DuplicateAssetError(
                f"Duplicate {asset_role} asset blocked: {path.name} ({digest})"
            )
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO registered_assets (sha256, asset_role, file_name, channel_tag, registered_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (digest, asset_role, path.name, channel_tag, now_iso),
            )
            conn.commit()
        return {
            "sha256": digest,
            "asset_role": asset_role,
            "file_name": path.name,
            "channel_tag": channel_tag,
            "registered_at": now_iso,
        }

    def list_entries(self, channel_tag: str | None = None) -> list[dict[str, Any]]:
        """Return all registered asset records, optionally filtered by channel_tag."""
        with self._connect() as conn:
            if channel_tag:
                rows = conn.execute(
                    "SELECT * FROM registered_assets WHERE channel_tag = ? ORDER BY registered_at DESC",
                    (channel_tag,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM registered_assets ORDER BY registered_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]
