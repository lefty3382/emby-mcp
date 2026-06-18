"""Async SQLite database access with safety-gated writes."""

import asyncio
import os
import shutil
import uuid
from datetime import datetime, timezone

import aiosqlite

from ..config import AppConfig
from .schema import (
    ITEMS_TABLE,
    LIST_ITEMS_TABLE,
    PLAYLIST_TYPE,
    SHARE_LEVEL_PRIVATE,
    USER_ITEM_SHARES_TABLE,
)

VALID_DBS = frozenset({"library.db", "users.db", "authentication.db", "activitylog.db"})


class EmbyDatabase:
    """Async SQLite access with safety-gated writes for Emby databases."""

    def __init__(self, config: AppConfig) -> None:
        self._db_path = config.db_path

    def _resolve_db(self, db_name: str) -> str:
        if db_name not in VALID_DBS:
            raise ValueError(
                f"Invalid database: {db_name}. Valid: {', '.join(sorted(VALID_DBS))}"
            )
        path = os.path.join(self._db_path, db_name)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Database not found: {path}")
        return path

    async def query(self, db_name: str, sql: str) -> list[dict]:
        stripped = sql.strip().upper()
        if not stripped.startswith("SELECT") and not stripped.startswith("PRAGMA"):
            raise ValueError("Only SELECT and PRAGMA statements are allowed for reads")

        db_path = self._resolve_db(db_name)
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql) as cursor:
                rows = await cursor.fetchall()
                if rows:
                    columns = [desc[0] for desc in cursor.description]
                    return [dict(zip(columns, row)) for row in rows]
                return []

    async def get_table_info(self, db_name: str) -> list[dict]:
        db_path = self._resolve_db(db_name)
        tables = []
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ) as cursor:
                table_names = [row[0] for row in await cursor.fetchall()]

            for name in table_names:
                async with db.execute(f"PRAGMA table_info('{name}')") as cursor:
                    columns = [
                        {"name": row[1], "type": row[2], "notnull": bool(row[3])}
                        for row in await cursor.fetchall()
                    ]
                async with db.execute(f"SELECT COUNT(*) FROM '{name}'") as cursor:
                    count = (await cursor.fetchone())[0]
                tables.append({"name": name, "columns": columns, "row_count": count})
        return tables

    async def get_db_stats(self, db_name: str) -> dict:
        db_path = self._resolve_db(db_name)
        wal_path = db_path + "-wal"
        shm_path = db_path + "-shm"

        stats = {
            "database": db_name,
            "path": db_path,
            "file_size_bytes": os.path.getsize(db_path),
            "file_size_mb": round(os.path.getsize(db_path) / (1024 * 1024), 2),
            "wal_exists": os.path.exists(wal_path),
            "shm_exists": os.path.exists(shm_path),
        }

        if os.path.exists(wal_path):
            stats["wal_size_bytes"] = os.path.getsize(wal_path)

        async with aiosqlite.connect(db_path) as db:
            async with db.execute("PRAGMA page_count") as c:
                stats["page_count"] = (await c.fetchone())[0]
            async with db.execute("PRAGMA page_size") as c:
                stats["page_size"] = (await c.fetchone())[0]
            async with db.execute("PRAGMA journal_mode") as c:
                stats["journal_mode"] = (await c.fetchone())[0]
            async with db.execute("PRAGMA integrity_check") as c:
                result = (await c.fetchone())[0]
                stats["integrity"] = result

        return stats

    async def get_internal_user_guid_map(self) -> dict[int, str]:
        """Map LocalUsersv2 integer Id -> 32-char lowercase GUID.

        The GUID is stored as a .NET little-endian byte blob; the REST /Users
        API exposes the same id in canonical 32-char hex form. User display
        names live in a non-UTF-8 binary blob, so we bridge int id -> guid here
        and resolve the name against /Users in the tool layer.
        """
        rows = await self.query(
            "users.db", "SELECT Id, hex(guid) AS guid_hex FROM LocalUsersv2"
        )
        mapping: dict[int, str] = {}
        for row in rows:
            uid = row.get("Id")
            guid_hex = row.get("guid_hex")
            if uid is None or not guid_hex:
                continue
            mapping[int(uid)] = uuid.UUID(bytes_le=bytes.fromhex(guid_hex)).hex
        return mapping

    async def get_playlists(self) -> list[dict]:
        """All playlists with owner_user_id (private share) and item_count."""
        sql = (
            "SELECT p.Id, p.Name, p.Path, s.UserId AS owner_user_id, "
            f"(SELECT COUNT(*) FROM {LIST_ITEMS_TABLE} li WHERE li.ListId = p.Id) "
            "AS item_count "
            f"FROM {ITEMS_TABLE} p "
            f"LEFT JOIN {USER_ITEM_SHARES_TABLE} s "
            f"ON s.ItemId = p.Id AND s.ShareLevel = {SHARE_LEVEL_PRIVATE} "
            f"WHERE p.type = {PLAYLIST_TYPE} "
            "ORDER BY item_count DESC"
        )
        return await self.query("library.db", sql)

    async def get_playlist_orphans(self) -> list[dict]:
        """Playlist entries whose target item no longer exists."""
        sql = (
            "SELECT li.ListId AS list_id, p.Name AS name, "
            "COUNT(*) AS orphaned_entries "
            f"FROM {LIST_ITEMS_TABLE} li "
            f"JOIN {ITEMS_TABLE} p ON p.Id = li.ListId "
            f"LEFT JOIN {ITEMS_TABLE} m ON m.Id = li.ListItemId "
            "WHERE m.Id IS NULL "
            "GROUP BY li.ListId, p.Name"
        )
        return await self.query("library.db", sql)

    async def get_playlist_summary(self, playlist_id: int) -> dict | None:
        """Name, path and item count for one playlist, or None if absent."""
        pid = int(playlist_id)
        rows = await self.query(
            "library.db",
            f"SELECT Id, Name, Path FROM {ITEMS_TABLE} "
            f"WHERE Id = {pid} AND type = {PLAYLIST_TYPE}",
        )
        if not rows:
            return None
        counts = await self.query(
            "library.db",
            f"SELECT COUNT(*) AS item_count FROM {LIST_ITEMS_TABLE} "
            f"WHERE ListId = {pid}",
        )
        summary = rows[0]
        summary["item_count"] = counts[0]["item_count"] if counts else 0
        return summary

    async def _check_container_stopped(self) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "ps", "--filter", "name=emby",
                "--format", "{{.Names}} {{.State}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode().strip()
            for line in output.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "emby" and parts[1] == "running":
                    raise RuntimeError(
                        "Emby container is running. Stop it before database writes: "
                        "docker compose stop emby"
                    )
        except FileNotFoundError:
            raise RuntimeError(
                "docker command not found — cannot verify container status"
            )

    async def _check_wal_clean(self, db_path: str) -> None:
        wal_path = db_path + "-wal"
        shm_path = db_path + "-shm"
        issues = []
        if os.path.exists(wal_path) and os.path.getsize(wal_path) > 0:
            issues.append(f"WAL file exists: {wal_path}")
        if os.path.exists(shm_path):
            issues.append(f"SHM file exists: {shm_path}")
        if issues:
            raise RuntimeError(
                "Database was not cleanly shut down. "
                f"Issues: {'; '.join(issues)}. "
                "Ensure Emby was stopped cleanly before writing."
            )

    async def _backup_db(self, db_path: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = f"{db_path}.backup.{timestamp}"
        shutil.copy2(db_path, backup_path)
        return backup_path

    async def _integrity_check(self, db_path: str) -> str:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("PRAGMA integrity_check") as cursor:
                result = (await cursor.fetchone())[0]
                return result

    async def write(
        self, db_name: str, sql: str, confirm: bool = False
    ) -> dict:
        db_path = self._resolve_db(db_name)

        # Gate 1: Preview mode
        if not confirm:
            preview = {
                "mode": "preview",
                "database": db_name,
                "sql": sql,
                "message": "Pass confirm=true to execute this write operation.",
                "safety_gates": [
                    "Container stopped check",
                    "WAL/SHM verification",
                    "Auto backup",
                    "Execute SQL",
                    "Integrity check",
                ],
            }
            stripped = sql.strip().upper()
            if stripped.startswith(("UPDATE", "DELETE")):
                try:
                    if stripped.startswith("UPDATE"):
                        parts = sql.strip().split("SET", 1)
                        table_part = parts[0].replace("UPDATE", "", 1).strip()
                        if "WHERE" in sql.upper():
                            where = sql[sql.upper().index("WHERE"):]
                            count_sql = f"SELECT COUNT(*) FROM {table_part} {where}"
                        else:
                            count_sql = f"SELECT COUNT(*) FROM {table_part}"
                    else:
                        parts = sql.strip().split("FROM", 1)
                        rest = parts[1].strip() if len(parts) > 1 else ""
                        count_sql = f"SELECT COUNT(*) FROM {rest}"

                    async with aiosqlite.connect(db_path) as db:
                        async with db.execute(count_sql) as cursor:
                            count = (await cursor.fetchone())[0]
                            preview["estimated_rows_affected"] = count
                except Exception:
                    preview["estimated_rows_affected"] = "unable to estimate"
            return preview

        # Gate 2: Container check
        await self._check_container_stopped()

        # Gate 3: WAL verification
        await self._check_wal_clean(db_path)

        # Gate 4: Auto backup
        backup_path = await self._backup_db(db_path)

        # Execute the write
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(sql)
            rows_affected = cursor.rowcount
            await db.commit()

        # Gate 5: Integrity check
        integrity = await self._integrity_check(db_path)

        result = {
            "mode": "executed",
            "database": db_name,
            "sql": sql,
            "rows_affected": rows_affected,
            "backup_path": backup_path,
            "integrity_check": integrity,
        }

        if integrity != "ok":
            result["warning"] = (
                f"Integrity check failed! Restore from backup: {backup_path}"
            )

        return result
