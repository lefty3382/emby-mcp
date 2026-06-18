# Emby Playlist & Schema-Rot Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the five `library.db` tools broken by Emby 4.9's table rename, make `list_playlists` surface all playlists with owners, and centralize the new schema names.

**Architecture:** Add a `schema.py` constants module (single source of truth for 4.9+ table names). Move new/rewritten playlist SQL into typed `EmbyDatabase` accessor methods so it is testable against a temp-SQLite fixture. Keep pure formatting/composition in module-level helper functions (unit-tested). `@mcp.tool` closures become thin glue over those tested pieces. The three simple table-name swaps stay inline, guarded by a regression test that asserts no pre-4.9 names remain in `src/`.

**Tech Stack:** Python 3.12, FastMCP 3.x, aiosqlite, aiohttp; pytest + pytest-asyncio for tests.

## Global Constraints

- Python `>=3.12`; runtime deps limited to `fastmcp>=3.1.0`, `aiohttp>=3.9.0`, `aiosqlite>=0.20.0`. Test-only deps: `pytest>=8.0`, `pytest-asyncio>=0.23`.
- Target the **Emby 4.9+ schema only** — no pre-4.9 back-compat, no runtime schema detection.
- New table-name literals go in `src/emby_mcp/clients/schema.py`; reference the constants, do not hardcode `"MediaItems"`/`"ListItems"` elsewhere.
- 4.9+ facts (verified live): playlists are `MediaItems.type = 16`; membership is `ListItems` (`ListId`=playlist `Id`, `ListItemId`=member `Id`, `ListItemOrder`); ownership is `UserItemShares` (`UserId`,`ItemId`,`ShareLevel=10000`); `MediaItems.OwnerId` is null for playlists; the DB integer `MediaItems.Id` equals the REST string `Id`.
- Final version is **1.3.0** across `CHANGELOG.md`, `pyproject.toml`, and `src/emby_mcp/__init__.py`.
- Commit after every task. Run `python -m pytest` from the repo root.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/emby_mcp/clients/schema.py` | **new** — 4.9+ table/column/value constants |
| `src/emby_mcp/clients/emby_database.py` | add typed playlist accessors + GUID map method |
| `src/emby_mcp/tools/playlist_tools.py` | DB-backed `list_playlists` + `_build_playlist_list`; `database` param |
| `src/emby_mcp/tools/database_tools.py` | fix `check_playlist_integrity`, `audit_paths`, `path_surgery`, `delete_playlist` + helpers |
| `src/emby_mcp/tools/reporting_tools.py` | fix `media_integrity_report` table name |
| `src/emby_mcp/server.py` | pass `database` into `register_playlist_tools` |
| `pyproject.toml` | version 1.3.0; pytest config + dev deps |
| `src/emby_mcp/__init__.py` | `__version__ = "1.3.0"` |
| `CHANGELOG.md` | `[1.3.0]` section |
| `tests/conftest.py` | **new** — temp-SQLite fixtures on the 4.9+ schema |
| `tests/test_*.py` | **new** — unit/integration tests |

---

### Task 1: Schema constants module

**Files:**
- Create: `src/emby_mcp/clients/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Produces: constants `ITEMS_TABLE="MediaItems"`, `LIST_ITEMS_TABLE="ListItems"`, `USER_ITEM_SHARES_TABLE="UserItemShares"`, `PLAYLIST_TYPE=16`, `SHARE_LEVEL_PRIVATE=10000`.

- [ ] **Step 1: Create the constants module**

Create `src/emby_mcp/clients/schema.py`:

```python
"""Emby 4.9+ library.db schema names (renamed from the pre-4.9 schema).

Pre-4.9 -> 4.9+:
  - The old item table was renamed; see ITEMS_TABLE below.
  - The old playlist-membership table was renamed; see LIST_ITEMS_TABLE
    (PlaylistId -> ListId; adds ListItemId, ListItemOrder).
  - Owner-private sharing is recorded in USER_ITEM_SHARES_TABLE.

Centralizing these names keeps a future Emby rename to a one-line change.
"""

ITEMS_TABLE = "MediaItems"                 # was the pre-4.9 base-item table
LIST_ITEMS_TABLE = "ListItems"             # was the pre-4.9 playlist-items table
USER_ITEM_SHARES_TABLE = "UserItemShares"

PLAYLIST_TYPE = 16                         # MediaItems.type value for playlists
SHARE_LEVEL_PRIVATE = 10000                # UserItemShares.ShareLevel for owner-private
```

> Note: the docstring deliberately avoids spelling the dead table names so the Task 8 regression test can scan the whole source tree.

- [ ] **Step 2: Write the value test**

Create `tests/test_schema.py`:

```python
from emby_mcp.clients import schema


def test_schema_constants():
    assert schema.ITEMS_TABLE == "MediaItems"
    assert schema.LIST_ITEMS_TABLE == "ListItems"
    assert schema.USER_ITEM_SHARES_TABLE == "UserItemShares"
    assert schema.PLAYLIST_TYPE == 16
    assert schema.SHARE_LEVEL_PRIVATE == 10000
```

- [ ] **Step 3: Run the test**

Run: `python -m pytest tests/test_schema.py -v`
Expected: PASS (Task 2 wires up pytest config; if pytest is not yet installed, do Task 2 Step 1 first, then return here).

- [ ] **Step 4: Commit**

```bash
git add src/emby_mcp/clients/schema.py tests/test_schema.py
git commit -m "feat: add central 4.9+ library.db schema constants"
```

---

### Task 2: Test harness + temp-DB fixtures

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/conftest.py`
- Test: `tests/test_fixtures.py`

**Interfaces:**
- Produces: pytest fixtures `data_dir` (a `Path` to a temp `data/` holding seeded `library.db` + `users.db`) and `emby_db` (an `EmbyDatabase` pointed at that temp dir). Seed data: playlist `Id=1` "Shared PL" (no share row), playlist `Id=2` "Private PL" (owned by user `2`, `ShareLevel=10000`); media items `100`,`101`; `ListItems` (1→100), (2→101), (2→999 ORPHAN); `LocalUsersv2` id `2` whose GUID canonicalizes to `db043bd8cb0a49b5b693dc3eceda6c17`.

- [ ] **Step 1: Install test deps and configure pytest**

Run: `python -m pip install "pytest>=8.0" "pytest-asyncio>=0.23"`

Then append to `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]
```

(`pythonpath = ["src"]` lets tests `import emby_mcp` without an editable install.)

- [ ] **Step 2: Write the fixtures**

Create `tests/conftest.py`:

```python
"""Shared pytest fixtures: temp Emby databases on the 4.9+ schema."""

import sqlite3
import uuid

import pytest

from emby_mcp.config import AppConfig
from emby_mcp.clients.emby_database import EmbyDatabase

# Internal user id 2 -> this canonical GUID -> display name "Kelly".
KELLY_GUID = "db043bd8cb0a49b5b693dc3eceda6c17"


def _build_library_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE MediaItems (
            Id INTEGER PRIMARY KEY, guid GUID, type INT,
            Path TEXT, Name TEXT, OwnerId INT, ParentId INT, data BLOB
        );
        CREATE TABLE ListItems (
            ListItemEntryId INTEGER PRIMARY KEY, ListId INT,
            ListItemId INT, ListItemOrder INT
        );
        CREATE TABLE UserItemShares (UserId INT, ItemId INT, ShareLevel INT);
        """
    )
    conn.executemany(
        "INSERT INTO MediaItems (Id, type, Name, Path) VALUES (?, ?, ?, ?)",
        [
            (1, 16, "Shared PL", "%AppDataPath%/playlists/Shared PL [playlist]/x.m3u"),
            (2, 16, "Private PL", "%AppDataPath%/userplaylists/Private PL [playlist]/x.m3u"),
            (100, 4, "Movie X", "/mnt/x.mkv"),
            (101, 4, "Movie Y", "/mnt/y.mkv"),
        ],
    )
    # PL1 -> item 100; PL2 -> item 101 + orphan 999 (no MediaItems row).
    conn.executemany(
        "INSERT INTO ListItems (ListId, ListItemId, ListItemOrder) VALUES (?, ?, ?)",
        [(1, 100, 0), (2, 101, 0), (2, 999, 1)],
    )
    conn.execute(
        "INSERT INTO UserItemShares (UserId, ItemId, ShareLevel) VALUES (2, 2, 10000)"
    )
    conn.commit()
    conn.close()


def _build_users_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE LocalUsersv2 (Id INTEGER PRIMARY KEY, guid GUID, data BLOB)"
    )
    conn.execute(
        "INSERT INTO LocalUsersv2 (Id, guid, data) VALUES (?, ?, ?)",
        (2, uuid.UUID(hex=KELLY_GUID).bytes_le, b"\x00binary-not-utf8"),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    _build_library_db(d / "library.db")
    _build_users_db(d / "users.db")
    return d


@pytest.fixture
def emby_db(tmp_path, data_dir):
    config = AppConfig(
        emby_host="test",
        emby_port=8096,
        emby_api_key="test",
        config_path=str(tmp_path),
        mcp_port=8486,
    )
    return EmbyDatabase(config)
```

- [ ] **Step 3: Write a fixture sanity test**

Create `tests/test_fixtures.py`:

```python
async def test_fixture_seeds_two_playlists(emby_db):
    rows = await emby_db.query(
        "library.db", "SELECT COUNT(*) AS c FROM MediaItems WHERE type = 16"
    )
    assert rows[0]["c"] == 2


def test_fixture_files_exist(data_dir):
    assert (data_dir / "library.db").exists()
    assert (data_dir / "users.db").exists()
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_fixtures.py tests/test_schema.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/conftest.py tests/test_fixtures.py
git commit -m "test: add pytest harness and temp-SQLite 4.9 schema fixtures"
```

---

### Task 3: `EmbyDatabase.get_internal_user_guid_map()`

**Files:**
- Modify: `src/emby_mcp/clients/emby_database.py`
- Test: `tests/test_user_guid_map.py`

**Interfaces:**
- Consumes: `schema` constants (none needed here), `self.query`.
- Produces: `async get_internal_user_guid_map(self) -> dict[int, str]` mapping `LocalUsersv2.Id` (int) to the 32-char lowercase GUID that `/Users` returns.

- [ ] **Step 1: Write the failing test**

Create `tests/test_user_guid_map.py`:

```python
async def test_guid_map_resolves_known_user(emby_db):
    mapping = await emby_db.get_internal_user_guid_map()
    assert mapping == {2: "db043bd8cb0a49b5b693dc3eceda6c17"}
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python -m pytest tests/test_user_guid_map.py -v`
Expected: FAIL — `AttributeError: 'EmbyDatabase' object has no attribute 'get_internal_user_guid_map'`.

- [ ] **Step 3: Implement the method**

In `src/emby_mcp/clients/emby_database.py`, add `import uuid` to the imports (after `import shutil`), and add this method to `EmbyDatabase` (e.g. after `get_db_stats`):

```python
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
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `python -m pytest tests/test_user_guid_map.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/emby_mcp/clients/emby_database.py tests/test_user_guid_map.py
git commit -m "feat: add EmbyDatabase.get_internal_user_guid_map for owner lookup"
```

---

### Task 4: Playlist read accessors

**Files:**
- Modify: `src/emby_mcp/clients/emby_database.py`
- Test: `tests/test_playlist_accessors.py`

**Interfaces:**
- Consumes: `schema` constants, `self.query`.
- Produces:
  - `async get_playlists(self) -> list[dict]` — rows with keys `Id`, `Name`, `Path`, `owner_user_id` (int or None), `item_count` (int), ordered by `item_count` DESC.
  - `async get_playlist_orphans(self) -> list[dict]` — rows with keys `list_id`, `name`, `orphaned_entries`.
  - `async get_playlist_summary(self, playlist_id: int) -> dict | None` — keys `Id`, `Name`, `Path`, `item_count`; `None` if no such playlist.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_playlist_accessors.py`:

```python
async def test_get_playlists_returns_shared_and_private(emby_db):
    rows = await emby_db.get_playlists()
    by_id = {r["Id"]: r for r in rows}
    assert set(by_id) == {1, 2}
    assert by_id[1]["owner_user_id"] is None       # globally shared
    assert by_id[2]["owner_user_id"] == 2           # owned by user 2
    assert by_id[1]["item_count"] == 1
    assert by_id[2]["item_count"] == 2              # 101 + orphan 999 both counted
    # ordered by item_count DESC
    assert [r["Id"] for r in rows] == [2, 1]


async def test_get_playlist_orphans_finds_missing_member(emby_db):
    rows = await emby_db.get_playlist_orphans()
    assert rows == [{"list_id": 2, "name": "Private PL", "orphaned_entries": 1}]


async def test_get_playlist_summary(emby_db):
    summary = await emby_db.get_playlist_summary(2)
    assert summary["Name"] == "Private PL"
    assert summary["item_count"] == 2
    assert await emby_db.get_playlist_summary(123456) is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_playlist_accessors.py -v`
Expected: FAIL — `AttributeError: ... 'get_playlists'`.

- [ ] **Step 3: Implement the accessors**

In `src/emby_mcp/clients/emby_database.py`, add the schema import near the top (after `from ..config import AppConfig`):

```python
from .schema import (
    ITEMS_TABLE,
    LIST_ITEMS_TABLE,
    PLAYLIST_TYPE,
    SHARE_LEVEL_PRIVATE,
    USER_ITEM_SHARES_TABLE,
)
```

Then add these three methods to `EmbyDatabase` (next to `get_internal_user_guid_map`):

```python
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
```

- [ ] **Step 4: Run to confirm pass**

Run: `python -m pytest tests/test_playlist_accessors.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/emby_mcp/clients/emby_database.py tests/test_playlist_accessors.py
git commit -m "feat: add playlist read accessors (list, orphans, summary)"
```

---

### Task 5: DB-backed `list_playlists` + server wiring

**Files:**
- Modify: `src/emby_mcp/tools/playlist_tools.py`
- Modify: `src/emby_mcp/server.py:50-53`
- Test: `tests/test_build_playlist_list.py`

**Interfaces:**
- Consumes: `database.get_playlists()`, `database.get_internal_user_guid_map()` (Tasks 3–4), `client.get("/emby/Users")`.
- Produces: module-level `_build_playlist_list(rows, id_to_guid, rest_users) -> list[dict]` (each dict: `id` str, `name`, `owner` str|None, `owner_user_id` int|None, `item_count`, `path`, `shared` bool); `register_playlist_tools(mcp, client, database)` (new 3rd param).

- [ ] **Step 1: Write the failing test**

Create `tests/test_build_playlist_list.py`:

```python
from emby_mcp.tools.playlist_tools import _build_playlist_list


def test_build_playlist_list_resolves_owner_and_shared_flag():
    rows = [
        {"Id": 2, "Name": "Private PL", "Path": "/p2", "owner_user_id": 2, "item_count": 5},
        {"Id": 1, "Name": "Shared PL", "Path": "/p1", "owner_user_id": None, "item_count": 3},
    ]
    id_to_guid = {2: "db043bd8cb0a49b5b693dc3eceda6c17"}
    # REST returns the GUID upper-cased here to prove normalization.
    rest_users = [{"Id": "DB043BD8CB0A49B5B693DC3ECEDA6C17", "Name": "Kelly"}]

    out = _build_playlist_list(rows, id_to_guid, rest_users)

    assert out[0] == {
        "id": "2",
        "name": "Private PL",
        "owner": "Kelly",
        "owner_user_id": 2,
        "item_count": 5,
        "path": "/p2",
        "shared": False,
    }
    assert out[1]["owner"] is None
    assert out[1]["shared"] is True
    assert out[1]["id"] == "1"
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_build_playlist_list.py -v`
Expected: FAIL — `ImportError: cannot import name '_build_playlist_list'`.

- [ ] **Step 3: Rewrite `playlist_tools.py`**

Replace the top of the file (imports + `list_playlists`) so it reads as follows. Add the `EmbyDatabase` import, the `_build_playlist_list` helper, the new `database` parameter, and the rewritten `list_playlists`. Leave `create_playlist`, `add_playlist_items`, and `list_collections` unchanged.

```python
"""Playlist & Collection tools — list, create, add items, collections."""

from fastmcp import FastMCP

from ..clients.emby_client import EmbyClient
from ..clients.emby_database import EmbyDatabase


def _build_playlist_list(
    rows: list[dict],
    id_to_guid: dict[int, str],
    rest_users: list[dict],
) -> list[dict]:
    """Shape DB playlist rows into tool output, resolving owner names.

    Args:
        rows: rows from EmbyDatabase.get_playlists().
        id_to_guid: {internal_user_id: 32-char guid} from get_internal_user_guid_map().
        rest_users: /emby/Users payload (each item has a 'Id' guid and 'Name').
    """
    guid_to_name = {(u.get("Id") or "").lower(): u.get("Name") for u in rest_users}
    playlists = []
    for row in rows:
        owner_id = row.get("owner_user_id")
        guid = id_to_guid.get(owner_id) if owner_id is not None else None
        playlists.append({
            "id": str(row.get("Id")),
            "name": row.get("Name"),
            "owner": guid_to_name.get(guid) if guid else None,
            "owner_user_id": owner_id,
            "item_count": row.get("item_count", 0),
            "path": row.get("Path"),
            "shared": owner_id is None,
        })
    return playlists


def register_playlist_tools(
    mcp: FastMCP, client: EmbyClient, database: EmbyDatabase
) -> None:
    """Register playlist and collection management tools."""

    @mcp.tool
    async def list_playlists() -> dict:
        """List all playlists (shared and owner-private) with owner and item count.

        Enumerated directly from library.db so owner-private playlists (invisible
        to the admin's user-scoped REST view) are included.
        """
        rows = await database.get_playlists()
        id_to_guid = await database.get_internal_user_guid_map()
        rest_users = await client.get("/emby/Users")
        playlists = _build_playlist_list(rows, id_to_guid, rest_users)
        return {"playlists": playlists, "count": len(playlists)}
```

- [ ] **Step 4: Note that `get_playlist_items` works for private playlists**

In the same file, update the `get_playlist_items` docstring first line to:

```python
        """Get all items in a playlist (works for owner-private playlists too).
```

- [ ] **Step 5: Wire `database` into registration**

In `src/emby_mcp/server.py`, change the playlist registration block (around lines 49–53):

```python
    try:
        from .tools.playlist_tools import register_playlist_tools
        register_playlist_tools(mcp, client, database)
    except ImportError:
        pass
```

- [ ] **Step 6: Run the test and a syntax/import check**

Run: `python -m pytest tests/test_build_playlist_list.py -v`
Expected: PASS.

Run: `python -c "import ast; ast.parse(open('src/emby_mcp/server.py').read()); ast.parse(open('src/emby_mcp/tools/playlist_tools.py').read()); print('ok')"`
Expected: `ok`.

- [ ] **Step 7: Commit**

```bash
git add src/emby_mcp/tools/playlist_tools.py src/emby_mcp/server.py tests/test_build_playlist_list.py
git commit -m "fix: list_playlists enumerates all playlists from DB with owners"
```

---

### Task 6: Rewrite `check_playlist_integrity`

**Files:**
- Modify: `src/emby_mcp/tools/database_tools.py`
- Test: `tests/test_format_orphans.py`

**Interfaces:**
- Consumes: `database.get_playlist_orphans()` (Task 4).
- Produces: module-level `_format_orphans(rows) -> dict` with keys `playlists_with_orphans` (list), `total_orphaned_entries` (int), `count` (int).

- [ ] **Step 1: Write the failing test**

Create `tests/test_format_orphans.py`:

```python
from emby_mcp.tools.database_tools import _format_orphans


def test_format_orphans_totals():
    rows = [
        {"list_id": 2, "name": "A", "orphaned_entries": 1},
        {"list_id": 5, "name": "B", "orphaned_entries": 3},
    ]
    out = _format_orphans(rows)
    assert out["playlists_with_orphans"] == rows
    assert out["total_orphaned_entries"] == 4
    assert out["count"] == 2


def test_format_orphans_empty():
    assert _format_orphans([]) == {
        "playlists_with_orphans": [],
        "total_orphaned_entries": 0,
        "count": 0,
    }
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_format_orphans.py -v`
Expected: FAIL — `ImportError: cannot import name '_format_orphans'`.

- [ ] **Step 3: Add the helper and rewrite the tool**

In `src/emby_mcp/tools/database_tools.py`, add this module-level helper (above `register_database_tools`). It uses no schema constants — the import is introduced in Task 7 where the constants are first used.

```python
def _format_orphans(rows: list[dict]) -> dict:
    """Shape get_playlist_orphans() rows into the integrity report."""
    return {
        "playlists_with_orphans": rows,
        "total_orphaned_entries": sum(r.get("orphaned_entries", 0) for r in rows),
        "count": len(rows),
    }
```

Replace the entire body of `check_playlist_integrity` (currently lines ~27–54) with:

```python
    @mcp.tool
    async def check_playlist_integrity() -> dict:
        """Find orphaned playlist entries.

        Pure DB check (4.9+ schema): flags ListItems rows whose target media
        item no longer exists in MediaItems.
        """
        rows = await database.get_playlist_orphans()
        return _format_orphans(rows)
```

- [ ] **Step 4: Run the test**

Run: `python -m pytest tests/test_format_orphans.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/emby_mcp/tools/database_tools.py tests/test_format_orphans.py
git commit -m "fix: check_playlist_integrity uses 4.9 ListItems/MediaItems orphan query"
```

---

### Task 7: Rewrite `delete_playlist`

**Files:**
- Modify: `src/emby_mcp/tools/database_tools.py`
- Test: `tests/test_delete_playlist_sql.py`

**Interfaces:**
- Consumes: `schema` constants, `database.get_playlist_summary()` (Task 4), `database.write()`.
- Produces: module-level `_playlist_delete_statements(playlist_id: int) -> list[tuple[str, str]]` — ordered `(result_key, sql)`: `("items_deleted", DELETE ListItems)`, `("shares_deleted", DELETE UserItemShares)`, `("playlist_deleted", DELETE MediaItems)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_delete_playlist_sql.py`:

```python
import sqlite3

from emby_mcp.tools.database_tools import _playlist_delete_statements


def test_delete_statements_shape_and_order():
    stmts = _playlist_delete_statements(2)
    keys = [k for k, _ in stmts]
    assert keys == ["items_deleted", "shares_deleted", "playlist_deleted"]
    assert "ListItems" in stmts[0][1] and "ListId = 2" in stmts[0][1]
    assert "UserItemShares" in stmts[1][1] and "ItemId = 2" in stmts[1][1]
    assert "MediaItems" in stmts[2][1] and "Id = 2" in stmts[2][1]


def test_delete_statements_remove_only_target(data_dir):
    conn = sqlite3.connect(data_dir / "library.db")
    for _, sql in _playlist_delete_statements(2):
        conn.execute(sql)
    conn.commit()

    def count(q):
        return conn.execute(q).fetchone()[0]

    # target playlist 2 fully removed
    assert count("SELECT COUNT(*) FROM MediaItems WHERE Id = 2") == 0
    assert count("SELECT COUNT(*) FROM ListItems WHERE ListId = 2") == 0
    assert count("SELECT COUNT(*) FROM UserItemShares WHERE ItemId = 2") == 0
    # playlist 1 untouched
    assert count("SELECT COUNT(*) FROM MediaItems WHERE Id = 1") == 1
    assert count("SELECT COUNT(*) FROM ListItems WHERE ListId = 1") == 1
    conn.close()
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_delete_playlist_sql.py -v`
Expected: FAIL — `ImportError: cannot import name '_playlist_delete_statements'`.

- [ ] **Step 3: Add the helper and rewrite the tool**

In `src/emby_mcp/tools/database_tools.py`, first add the schema import below the existing imports (these constants are used by this task and Task 8):

```python
from ..clients.schema import (
    ITEMS_TABLE,
    LIST_ITEMS_TABLE,
    USER_ITEM_SHARES_TABLE,
)
```

Then add this module-level helper (next to `_format_orphans`):

```python
def _playlist_delete_statements(playlist_id: int) -> list[tuple[str, str]]:
    """(result_key, DELETE sql) tuples to remove a playlist and its links."""
    pid = int(playlist_id)
    return [
        ("items_deleted", f"DELETE FROM {LIST_ITEMS_TABLE} WHERE ListId = {pid}"),
        ("shares_deleted", f"DELETE FROM {USER_ITEM_SHARES_TABLE} WHERE ItemId = {pid}"),
        ("playlist_deleted", f"DELETE FROM {ITEMS_TABLE} WHERE Id = {pid}"),
    ]
```

Replace the entire `delete_playlist` tool (currently lines ~218–269) with:

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_delete_playlist_sql.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/emby_mcp/tools/database_tools.py tests/test_delete_playlist_sql.py
git commit -m "fix: delete_playlist uses 4.9 tables, integer Id, and clears shares"
```

---

### Task 8: Table-name swaps + regression guard

**Files:**
- Modify: `src/emby_mcp/tools/database_tools.py` (`audit_paths`, `path_surgery`)
- Modify: `src/emby_mcp/tools/reporting_tools.py` (`media_integrity_report`)
- Test: `tests/test_no_dead_tables.py`

**Interfaces:**
- Consumes: `ITEMS_TABLE` (already imported in `database_tools.py` from Task 7; add the import to `reporting_tools.py`).
- Produces: a regression test asserting no `src/` module (except `schema.py`) contains the pre-4.9 table names.

- [ ] **Step 1: Write the failing regression test**

Create `tests/test_no_dead_tables.py`:

```python
import pathlib

DEAD_NAMES = ("TypedBaseItems", "PlaylistItems")


def test_no_pre_4_9_table_names_in_src():
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "emby_mcp"
    offenders = []
    for path in src.rglob("*.py"):
        if path.name == "schema.py":  # documents the rename intentionally
            continue
        text = path.read_text(encoding="utf-8")
        for dead in DEAD_NAMES:
            if dead in text:
                offenders.append(f"{path.name}: {dead}")
    assert not offenders, f"pre-4.9 table names still present: {offenders}"
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_no_dead_tables.py -v`
Expected: FAIL — offenders list includes `audit_paths`/`path_surgery` (`database_tools.py`) and `reporting_tools.py` references.

- [ ] **Step 3: Swap `audit_paths`**

In `src/emby_mcp/tools/database_tools.py`, replace the `audit_paths` query (currently line ~112–115):

```python
        rows = await database.query(
            "library.db",
            f"SELECT guid, Name, Path FROM {ITEMS_TABLE} "
            "WHERE Path IS NOT NULL AND Path != '' LIMIT 5000",
        )
```

- [ ] **Step 4: Swap `path_surgery` (4 occurrences)**

In the same file, in `path_surgery`, replace the two preview COUNT queries:

```python
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
```

and the two UPDATE statements:

```python
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
```

- [ ] **Step 5: Swap `media_integrity_report`**

In `src/emby_mcp/tools/reporting_tools.py`, add the import near the other imports at the top of the file:

```python
from ..clients.schema import ITEMS_TABLE
```

Replace the `media_integrity_report` SQL (currently line ~149):

```python
        sql = f"SELECT guid, Name, Path FROM {ITEMS_TABLE} WHERE Path IS NOT NULL AND Path != ''"
```

- [ ] **Step 6: Run the regression test + full suite**

Run: `python -m pytest tests/test_no_dead_tables.py -v`
Expected: PASS.

Run: `python -m pytest -v`
Expected: PASS (all tests).

- [ ] **Step 7: Commit**

```bash
git add src/emby_mcp/tools/database_tools.py src/emby_mcp/tools/reporting_tools.py tests/test_no_dead_tables.py
git commit -m "fix: repoint audit_paths, path_surgery, media_integrity_report to MediaItems"
```

---

### Task 9: Version bump + changelog

**Files:**
- Modify: `pyproject.toml:7`
- Modify: `src/emby_mcp/__init__.py:3`
- Modify: `CHANGELOG.md`

**Interfaces:** none (metadata only).

- [ ] **Step 1: Bump `pyproject.toml`**

Change `version = "1.1.0"` to:

```toml
version = "1.3.0"
```

- [ ] **Step 2: Bump `__init__.py`**

Change `__version__ = "1.0.0"` to:

```python
__version__ = "1.3.0"
```

- [ ] **Step 3: Add the changelog section**

Insert at the top of `CHANGELOG.md`, directly under the `# Changelog` intro lines and above `## [1.2.0]`:

```markdown
## [1.3.0] - 2026-06-17

### Fixed
- **list_playlists**: Was returning only 3 of 35 playlists. It queried the user-scoped REST endpoint `/Users/{admin}/Items`, which only surfaces globally-shared playlists under `/playlists/`; the owner-private playlists (`/userplaylists/`, `UserItemShares.ShareLevel=10000`) were invisible to that context. Now enumerated directly from `library.db` and returns every playlist with `owner`, `owner_user_id`, `item_count`, and a `shared` flag.
- **check_playlist_integrity**: Errored `no such table: TypedBaseItems` on Emby 4.9+. Rewritten to the renamed schema (`ListItems` JOIN `MediaItems`); now reports orphaned playlist entries (members whose target item no longer exists).
- **audit_paths, media_integrity_report, path_surgery, delete_playlist**: All referenced the pre-4.9 `TypedBaseItems`/`PlaylistItems` tables and were broken on Emby 4.9+. Repointed to `MediaItems`/`ListItems`. `delete_playlist` now keys off the integer playlist `Id` (matching `list_playlists`) and also clears the playlist's `UserItemShares` row to avoid an orphaned share.

### Added
- **clients/schema.py**: Central constants for Emby 4.9+ `library.db` table/column names, so a future schema rename is a one-line change.
- **Owner resolution**: `EmbyDatabase.get_internal_user_guid_map()` bridges the integer `UserId` in `UserItemShares` to the canonical GUID `/Users` exposes, letting `list_playlists` surface owner display names.
- **Test suite**: pytest + pytest-asyncio with a temp-SQLite fixture on the 4.9+ schema, covering the owner GUID map, playlist enumeration, orphan detection, and the destructive `delete_playlist` SQL.

### Changed
- **Version drift resolved**: synced `pyproject.toml` (was 1.1.0) and `__init__.py` (was 1.0.0) to 1.3.0.

### Context
- Verified against a live Emby 4.9.5.0 server: 35 playlists present while `list_playlists` returned 3, and `check_playlist_integrity` errored on `TypedBaseItems`. `get_playlist_items` was also flagged in the report but proved to already work for owner-private playlists (returned all 314 items of a private playlist) — the only barrier was ID discovery, which the `list_playlists` fix resolves, so no change was needed there.
```

- [ ] **Step 4: Verify versions agree**

Run: `grep -n '^version' pyproject.toml && grep -n '__version__' src/emby_mcp/__init__.py`
Expected: both lines show `1.3.0` (`version = "1.3.0"` and `__version__ = "1.3.0"`).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/emby_mcp/__init__.py CHANGELOG.md
git commit -m "chore: release 1.3.0 — playlist & schema-rot fixes"
```

---

### Task 10: Live verification (manual, post-deploy)

**Files:** none — runtime verification against the real server after this branch is deployed.

**Interfaces:** none.

- [ ] **Step 1: Full local test suite is green**

Run: `python -m pytest -v`
Expected: PASS (all tests across all files).

- [ ] **Step 2: Deploy the branch to the running MCP container**

Rebuild/redeploy the emby-mcp container from this branch (out of band — e.g. `docker compose build emby-mcp && docker compose up -d emby-mcp`, per the deployment in `docker-compose.yaml`). The MCP tools exposed to the assistant reflect the *deployed* image, not the working tree, so this step must happen before the checks below mean anything.

- [ ] **Step 3: Verify `list_playlists`**

Call the `list_playlists` MCP tool.
Expected: `count` is 35 (not 3); private playlists appear with a non-null `owner` and `owner_user_id`; the three globally-shared ones have `shared: true` and `owner: null`.

- [ ] **Step 4: Verify `check_playlist_integrity`**

Call the `check_playlist_integrity` MCP tool.
Expected: no error (no `TypedBaseItems`); returns `playlists_with_orphans`, `total_orphaned_entries`, `count` (currently expected clean — 0 — but a non-zero result is a valid real finding, not a failure).

- [ ] **Step 5: Verify `get_playlist_items` on a private playlist**

Take a private playlist `id` from Step 3 and call `get_playlist_items` with it.
Expected: returns its items (non-empty), confirming private playlists are readable once their IDs are discoverable.

- [ ] **Step 6: Finish the branch**

Use the superpowers:finishing-a-development-branch skill to merge/PR `fix/playlist-schema-rot`.

---

## Notes for the implementer

- **Do not** add tests that invoke the `@mcp.tool` closures directly — they are thin glue over the tested accessors/helpers and are validated live in Task 10. The destructive write tools (`path_surgery`, `delete_playlist`) are intentionally verified only via the fixture SQL, never against the live DB.
- `database.write()` runs five safety gates (Emby-stopped check, WAL check, backup, execute, integrity); that path is unchanged and is not exercised in unit tests.
- Keep SQL identifiers coming from constants; the only user-supplied value interpolated into SQL is the playlist id, which is coerced through `int()` first.
