# Design: Fix playlist tools & pre-4.9 schema rot

**Date:** 2026-06-17
**Status:** Approved (pending spec review)
**Target version:** 1.3.0

## Problem

A bug report (playlist-related) flagged three issues in the emby-mcp server.
Verification against the live server (Emby **4.9.5.0**) confirmed two real bugs,
proved the third is a non-issue, and revealed that the root cause of bug 2 is a
schema rename that breaks **five** tools, not one.

Emby 4.9 renamed core `library.db` tables. The repo's raw SQL still uses the
pre-4.9 names, so every raw-SQL tool that references them errors out:

| Pre-4.9 name      | 4.9+ name          | Notes                                                        |
| ----------------- | ------------------ | ----------------------------------------------------------- |
| `TypedBaseItems`  | `MediaItems`       | `Id` (INTEGER PK), `guid` (GUID), `type` (INT), `Path`, `Name`, `OwnerId`, `data`, `ParentId` |
| `PlaylistItems`   | `ListItems`        | cols: `ListItemEntryId` (PK), `ListId`, `ListItemId`, `ListItemOrder` |
| —                 | `UserItemShares`   | cols: `UserId` (INT), `ItemId` (INT), `ShareLevel` (INT)    |

Additional schema facts verified live:

- `MediaItems.type = 16` identifies playlists. `type` is an **INT**, so the old
  `type LIKE '%Playlist%'` predicate would fail even after a bare table rename.
- `MediaItems.OwnerId` is **null** for all playlists — ownership lives only in
  `UserItemShares` (`ShareLevel = 10000` = owner-private).
- Playlist item membership lives in `ListItems` (`ListId` = playlist
  `MediaItems.Id`, `ListItemId` = member `MediaItems.Id`, `ListItemOrder` = order).
- The DB integer `MediaItems.Id` is the same id the REST API returns as its
  string `Id` (e.g. DB `509363` ↔ REST `"509363"`).

## Bug triage (verified against live 4.9.5.0 server)

### Bug 1 — `list_playlists` returns 3 of 35 — REAL

Root cause: the tool calls the **user-scoped** REST endpoint
`/Users/{admin}/Items`, which only returns the 3 globally-shared playlists under
`/playlists/`. The other 32 are owner-private (`/userplaylists/`,
`UserItemShares.ShareLevel = 10000`, owned across ~8 users) and are invisible to
the admin's user-scoped view. A direct DB query returns all 35.

### Bug 2 — `check_playlist_integrity` broken — REAL, and broader

It errors `no such table: TypedBaseItems`. The same dead names break four more
tools:

- `check_playlist_integrity` — `TypedBaseItems` + `PlaylistItems`
- `audit_paths` — `TypedBaseItems`
- `media_integrity_report` — `TypedBaseItems`
- `path_surgery` — `TypedBaseItems` (×4, including writes)
- `delete_playlist` — `TypedBaseItems` + `PlaylistItems`

### Bug 3 — `get_playlist_items` on a private playlist — NOT a bug

Verified: `get_playlist_items(661634)` (a private playlist owned by Wade Newman)
returned all 314 items via REST. The admin API key reads any playlist by ID;
those 32 were only unreachable because `list_playlists` never surfaced their IDs.
**No code change** — fixing Bug 1 unblocks ID discovery. Confirm live post-change.

## Decisions

1. **Scope:** fix all five broken tools (the two from the report plus
   `audit_paths`, `media_integrity_report`, `path_surgery`, `delete_playlist`).
2. **Schema target:** Emby 4.9+ only, via a central constants module. No runtime
   schema detection, no pre-4.9 back-compat.
3. **`delete_playlist` identifier:** standardize on the integer `Id` that
   `list_playlists` surfaces (was mixing `guid` and the dead `PlaylistItems`).
4. **Testing:** add a small pytest suite with a temp-SQLite fixture — the only
   safe way to verify the destructive write-path SQL without mutating the live DB.

## Design

### 1. New module `src/emby_mcp/clients/schema.py`

Single source of truth for 4.9+ table/column constants:

```python
"""Emby 4.9+ library.db schema names (renamed from the pre-4.9 schema).

Pre-4.9 -> 4.9+:
  TypedBaseItems -> MediaItems
  PlaylistItems  -> ListItems   (PlaylistId -> ListId; adds ListItemId, ListItemOrder)
  (new)          -> UserItemShares
"""

ITEMS_TABLE = "MediaItems"             # was TypedBaseItems
LIST_ITEMS_TABLE = "ListItems"         # was PlaylistItems
USER_ITEM_SHARES_TABLE = "UserItemShares"

PLAYLIST_TYPE = 16                     # MediaItems.type value for playlists
SHARE_LEVEL_PRIVATE = 10000            # UserItemShares.ShareLevel for owner-private
```

All five tools import these instead of hardcoding literals. A future Emby rename
becomes a one-line edit here.

### 2. `list_playlists` — DB-backed (`tools/playlist_tools.py`)

Replace the user-scoped REST call with the verified DB query:

```sql
SELECT p.Id,
       p.Name,
       p.Path,
       s.UserId AS owner_user_id,
       (SELECT COUNT(*) FROM ListItems li WHERE li.ListId = p.Id) AS item_count
FROM MediaItems p
LEFT JOIN UserItemShares s ON s.ItemId = p.Id AND s.ShareLevel = 10000
WHERE p.type = 16
ORDER BY item_count DESC;
```

(Table names / constants come from `schema.py`.) For each row, return:

| field           | source                                                   |
| --------------- | -------------------------------------------------------- |
| `id`            | `str(p.Id)` (matches REST id format)                     |
| `name`          | `p.Name`                                                 |
| `owner`         | owner-name map lookup on `owner_user_id` (null if none)  |
| `owner_user_id` | `s.UserId` (null for the 3 globally-shared playlists)    |
| `item_count`    | `ListItems` count                                        |
| `path`          | `p.Path` (raw, keeps `%AppDataPath%` placeholder)        |
| `shared`        | `owner_user_id is None` (true = globally shared)         |

Returns `{"playlists": [...], "count": 35}`.

`register_playlist_tools` gains a `database` parameter (wired in `server.py`).

### 3. Owner-name mapping helper

Owners are integer `UserId`s; the display name lives in a binary blob
(`LocalUsersv2.data`) that is not UTF-8 / not JSON, so it cannot be read in SQL.
Map int id → name through the GUID:

- New `EmbyDatabase.get_internal_user_guid_map() -> dict[int, str]`:
  runs `SELECT Id, hex(guid) FROM LocalUsersv2` and converts each blob with
  `uuid.UUID(bytes_le=bytes.fromhex(hex_guid)).hex` (the .NET GUID byte-swap).
  Returns `{int_id: guid_n}` where `guid_n` is the 32-char lowercase form the
  REST `/Users` API uses. Verified: id 2 → `db043bd8...` (Kelly),
  id 37 → `6ccbfb36...` (Wade Newman).
- In `list_playlists`: fetch `/emby/Users` → `{guid_n: name}`, compose with the
  guid map → `{int_id: name}`, then resolve each playlist's `owner_user_id`.

### 4. `check_playlist_integrity` — corrected orphan query (`tools/database_tools.py`)

Drop the `TypedBaseItems`/`PlaylistItems` logic. Use the tested query:

```sql
SELECT li.ListId, p.Name, COUNT(*) AS orphaned_entries
FROM ListItems li
JOIN MediaItems p ON p.Id = li.ListId
LEFT JOIN MediaItems m ON m.Id = li.ListItemId
WHERE m.Id IS NULL
GROUP BY li.ListId, p.Name;
```

Return `{"playlists_with_orphans": [{list_id, name, orphaned_entries}, ...],
"total_orphaned_entries": N, "count": len}`. (Live DB currently returns 0
orphans — the query runs clean.) Update the docstring to describe the
DB-only orphan check.

### 5. `audit_paths`, `media_integrity_report`, `path_surgery`

Mechanical swap of `TypedBaseItems` → `ITEMS_TABLE` (from `schema.py`):

- `audit_paths` (`database_tools.py`) — 1 SELECT.
- `media_integrity_report` (`reporting_tools.py`) — 1 SELECT (`ParentId` filter
  still valid).
- `path_surgery` (`database_tools.py`) — 4 occurrences: 2 preview COUNT queries
  + 2 UPDATE statements (`Path` text + `data` blob; both columns confirmed).

No behavior change beyond the table name.

### 6. `delete_playlist` — tables + identifier + share cleanup (`tools/database_tools.py`)

Rewrite around the integer `Id`:

- **Resolve / preview:** `SELECT Id, Name, Path FROM MediaItems WHERE Id = ? AND type = 16`;
  item count via `SELECT COUNT(*) FROM ListItems WHERE ListId = ?`. Return the
  existing preview shape (name, id, item_count, message).
- **Execute** (each through `database.write`, keeping all 5 safety gates):
  1. `DELETE FROM ListItems WHERE ListId = ?`
  2. `DELETE FROM UserItemShares WHERE ItemId = ?`  *(new — removes the
     owner-private share row so it is not orphaned)*
  3. `DELETE FROM MediaItems WHERE Id = ?`
- Docstring: clarify `playlist_id` is the integer `Id` from `list_playlists`.

### 7. `get_playlist_items` — no change

Verified working for private playlists. Confirm live after Bug 1 lands. Optional:
one docstring line noting it works for owner-private playlists too.

### 8. `server.py`

`register_playlist_tools(mcp, client, database)` — pass the existing `database`
instance (already constructed for the other tool groups).

### 9. Versioning & changelog

Bump to **1.3.0** and resolve the drift:

- `CHANGELOG.md` — new `[1.3.0]` section in the existing Fixed / Changed /
  Context style.
- `pyproject.toml` — `version = "1.3.0"` (currently 1.1.0).
- `src/emby_mcp/__init__.py` — `__version__ = "1.3.0"` (currently 1.0.0).

## Testing

New `tests/` directory using **pytest + pytest-asyncio** (added to dev deps in
`pyproject.toml`). A fixture builds a temp SQLite file seeding the 4.9 schema
(`MediaItems`, `ListItems`, `UserItemShares`) plus a minimal `users.db`
(`LocalUsersv2`) with sample rows:

- a globally-shared playlist (no share row),
- an owner-private playlist (a `UserItemShares` row, `ShareLevel = 10000`),
- a deliberately injected orphan `ListItems` row (member id with no `MediaItems`),
- a `LocalUsersv2` row with a known `guid` blob whose byte-swap is asserted.

Test coverage:

1. **GUID → name map** — `get_internal_user_guid_map()` returns the expected
   `{int_id: guid_n}`; the byte-swap matches the known canonical GUID.
2. **`list_playlists` DB query** — returns both shared and private playlists,
   correct `item_count`, `owner_user_id`, and `shared` flag.
3. **`check_playlist_integrity`** — the corrected SQL finds exactly the injected
   orphan.
4. **`delete_playlist`** — after execute, rows are gone from `ListItems`,
   `UserItemShares`, and `MediaItems` for the target id (and untouched for others).

**Live verification (post-implementation, read-only via the running MCP):**
re-run `list_playlists` (expect 35 with owners), `check_playlist_integrity`
(expect clean), and `get_playlist_items` on a private id (expect full list).
Write-path tools (`path_surgery`, `delete_playlist`) are verified only via the
fixture — they require Emby stopped and mutate data, so they are not exercised
against the live DB.

## Out of scope

- Pre-4.9 schema support / runtime schema detection (dropped per decision).
- Resolving `%AppDataPath%` in surfaced playlist paths (left raw/informational).
- REST-based tools that use no raw SQL (unaffected by the rename).

## Files touched

| File                                        | Change                                          |
| ------------------------------------------- | ----------------------------------------------- |
| `src/emby_mcp/clients/schema.py`            | **new** — table/column/value constants          |
| `src/emby_mcp/clients/emby_database.py`     | add `get_internal_user_guid_map()`              |
| `src/emby_mcp/tools/playlist_tools.py`      | DB-backed `list_playlists` + owner map; `database` param; optional `get_playlist_items` docstring |
| `src/emby_mcp/tools/database_tools.py`      | fix `check_playlist_integrity`, `audit_paths`, `path_surgery`, `delete_playlist` |
| `src/emby_mcp/tools/reporting_tools.py`     | fix `media_integrity_report`                    |
| `src/emby_mcp/server.py`                    | pass `database` to `register_playlist_tools`    |
| `pyproject.toml`                            | version 1.3.0; pytest dev deps                  |
| `src/emby_mcp/__init__.py`                  | `__version__ = "1.3.0"`                          |
| `CHANGELOG.md`                              | `[1.3.0]` section                               |
| `tests/` (+ fixture)                        | **new** — pytest suite                          |
