"""Database tools — query, schema, path audit, Emby Connect, safety-gated writes."""

from fastmcp import FastMCP

from ..clients.emby_client import EmbyClient
from ..clients.emby_database import EmbyDatabase
from ..clients.schema import (
    ITEMS_TABLE,
    LIST_ITEMS_TABLE,
    USER_ITEM_SHARES_TABLE,
)
from ..config import AppConfig


def _playlist_delete_statements(playlist_id: int) -> list[tuple[str, str]]:
    """(result_key, DELETE sql) tuples to remove a playlist and its links."""
    pid = int(playlist_id)
    return [
        ("items_deleted", f"DELETE FROM {LIST_ITEMS_TABLE} WHERE ListId = {pid}"),
        ("shares_deleted", f"DELETE FROM {USER_ITEM_SHARES_TABLE} WHERE ItemId = {pid}"),
        ("playlist_deleted", f"DELETE FROM {ITEMS_TABLE} WHERE Id = {pid}"),
    ]


def _build_connect_status(users: list[dict]) -> list[dict]:
    """Shape REST /Users rows into Emby Connect linkage records.

    Sourced from REST, not users.db: LocalUsersv2 is (Id, guid, data BLOB),
    so every user attribute is serialized inside the BLOB and unreachable by
    column name. Emby 4.9 exposes no ConnectUserId, so it is not reported.
    """
    result = []
    for u in users:
        connect_name = u.get("ConnectUserName")
        has_password = bool(u.get("HasConfiguredPassword") or u.get("HasPassword"))
        result.append({
            "id": u.get("Id"),
            "name": u.get("Name"),
            "connect_user_name": connect_name,
            "connect_link_type": u.get("ConnectLinkType"),
            "has_local_password": has_password,
            "last_login_date": u.get("LastLoginDate"),
            "last_activity_date": u.get("LastActivityDate"),
            "auth_method": (
                "connect+local" if connect_name and has_password
                else "connect" if connect_name
                else "local" if has_password
                else "none"
            ),
        })
    return result


def _format_orphans(rows: list[dict]) -> dict:
    """Shape get_playlist_orphans() rows into the integrity report."""
    return {
        "playlists_with_orphans": rows,
        "total_orphaned_entries": sum(r.get("orphaned_entries", 0) for r in rows),
        "count": len(rows),
    }


def register_database_tools(
    mcp: FastMCP, client: EmbyClient, database: EmbyDatabase, config: AppConfig
) -> None:
    """Register database inspection and write tools."""

    @mcp.tool
    async def query_database(db_name: str, sql: str) -> dict:
        """Run a read-only SELECT query against any Emby database.

        Args:
            db_name: Database file — 'library.db', 'users.db', 'authentication.db', or 'activitylog.db'.
            sql: SQL SELECT or PRAGMA statement.
        """
        try:
            rows = await database.query(db_name, sql)
            return {"rows": rows, "count": len(rows), "database": db_name}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool
    async def check_playlist_integrity() -> dict:
        """Find orphaned playlist entries.

        Pure DB check (4.9+ schema): flags ListItems rows whose target media
        item no longer exists in MediaItems.
        """
        rows = await database.get_playlist_orphans()
        return _format_orphans(rows)

    @mcp.tool
    async def get_emby_connect_status() -> dict:
        """Get Emby Connect linkage status for all users.

        Shows: Connect username, link type, auth method, last login,
        and local password status.
        """
        try:
            users = await client.get("/emby/Users")
        except Exception as e:
            return {"error": str(e)}

        result = _build_connect_status(users)
        return {
            "users": result,
            "count": len(result),
            "connect_linked": sum(1 for r in result if r["connect_user_name"]),
        }

    @mcp.tool
    async def audit_paths(expected_prefixes: list[str] | None = None) -> dict:
        """Scan all media paths in library.db and flag mismatches.

        Args:
            expected_prefixes: List of expected path prefixes (e.g., ['/mnt/movies', '/mnt/tv']).
                If omitted, uses paths from the EMBY_MEDIA_PATHS environment variable.
        """
        if expected_prefixes is None:
            expected_prefixes = config.media_paths
        if not expected_prefixes:
            return {"error": "No expected_prefixes provided and EMBY_MEDIA_PATHS not configured."}

        rows = await database.query(
            "library.db",
            f"SELECT guid, Name, Path FROM {ITEMS_TABLE} "
            "WHERE Path IS NOT NULL AND Path != '' LIMIT 5000",
        )

        matched = 0
        mismatched = []
        for row in rows:
            path = row.get("Path", "")
            if any(path.startswith(prefix) for prefix in expected_prefixes):
                matched += 1
            else:
                mismatched.append({
                    "name": row.get("Name"),
                    "path": path,
                    "guid": row.get("guid"),
                })

        return {
            "total_checked": len(rows),
            "matched": matched,
            "mismatched_count": len(mismatched),
            "expected_prefixes": expected_prefixes,
            "mismatched_items": mismatched[:50],  # Cap at 50 for readability
        }

    @mcp.tool
    async def get_db_table_info(db_name: str) -> dict:
        """List all tables, columns, and row counts for an Emby database.

        Args:
            db_name: Database file — 'library.db', 'users.db', 'authentication.db', or 'activitylog.db'.
        """
        try:
            tables = await database.get_table_info(db_name)
            return {"database": db_name, "tables": tables, "table_count": len(tables)}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool
    async def get_db_statistics(db_name: str) -> dict:
        """Get database file size, WAL status, page count, and integrity.

        Args:
            db_name: Database file — 'library.db', 'users.db', 'authentication.db', or 'activitylog.db'.
        """
        try:
            return await database.get_db_stats(db_name)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool
    async def path_surgery(
        old_prefix: str,
        new_prefix: str,
        confirm: bool = False,
    ) -> dict:
        """Find and replace path prefixes in library.db — both TEXT and BLOB fields.

        Used during migrations to update media paths (e.g., Windows UNC to Linux NFS).
        Safety-gated: requires Emby stopped, creates backup, runs integrity check.

        Args:
            old_prefix: Path prefix to find (e.g., '\\\\\\\\server\\\\share\\\\Media').
            new_prefix: Replacement prefix (e.g., '/mnt/media/movies').
            confirm: Must be true to execute. False returns a preview.
        """
        if not confirm:
            # Preview: count matching rows
            text_rows = await database.query(
                "library.db",
                f"SELECT COUNT(*) as count FROM {ITEMS_TABLE} "
                f"WHERE Path LIKE '{old_prefix}%'",
            )
            blob_rows = await database.query(
                "library.db",
                f"SELECT COUNT(*) as count FROM {ITEMS_TABLE} "
                f"WHERE CAST(data AS TEXT) LIKE '%{old_prefix}%'",
            )
            return {
                "mode": "preview",
                "old_prefix": old_prefix,
                "new_prefix": new_prefix,
                "text_field_matches": text_rows[0]["count"] if text_rows else 0,
                "blob_field_matches": blob_rows[0]["count"] if blob_rows else 0,
                "message": "Pass confirm=true to execute path surgery.",
            }

        # Execute with safety gates
        text_sql = (
            f"UPDATE {ITEMS_TABLE} SET Path = REPLACE(Path, '{old_prefix}', '{new_prefix}') "
            f"WHERE Path LIKE '{old_prefix}%'"
        )
        text_result = await database.write("library.db", text_sql, confirm=True)

        blob_sql = (
            f"UPDATE {ITEMS_TABLE} SET data = CAST("
            f"REPLACE(CAST(data AS TEXT), '{old_prefix}', '{new_prefix}') AS BLOB) "
            f"WHERE CAST(data AS TEXT) LIKE '%{old_prefix}%'"
        )
        blob_result = await database.write("library.db", blob_sql, confirm=True)

        return {
            "mode": "executed",
            "text_update": text_result,
            "blob_update": blob_result,
        }

    @mcp.tool
    async def delete_playlist(
        playlist_id: str,
        confirm: bool = False,
    ) -> dict:
        """Delete a playlist and its item/share rows from library.db.

        Cannot be done via REST API. Safety-gated: requires Emby stopped,
        creates backup, runs integrity check.

        Args:
            playlist_id: The integer playlist Id (as returned by list_playlists).
            confirm: Must be true to execute. False returns a preview.
        """
        try:
            pid = int(playlist_id)
        except (TypeError, ValueError):
            return {"error": f"playlist_id must be an integer Id: {playlist_id!r}"}

        if not confirm:
            summary = await database.get_playlist_summary(pid)
            if not summary:
                return {"error": f"No playlist found with Id: {pid}"}
            return {
                "mode": "preview",
                "playlist_name": summary.get("Name"),
                "playlist_id": pid,
                "item_count": summary.get("item_count", 0),
                "message": "Pass confirm=true to delete this playlist.",
            }

        results: dict = {"mode": "executed", "playlist_id": pid}
        for key, sql in _playlist_delete_statements(pid):
            results[key] = await database.write("library.db", sql, confirm=True)
        return results
