# `get_server_info` reports `has_premiere: false` on a licensed server, and `get_emby_connect_status` returns all-null user fields

**Status:** Resolved (2026-09-02, v1.4.0)
**Reported:** 2026-09-02
**Component:** `get_server_info`, `get_emby_connect_status`
**Severity:** High — both tools returned confident, wrong answers about licence and user state

## Summary

Two unrelated tools returned well-formed output that was entirely false, in both cases because they read field names Emby 4.9 does not provide. Reading an absent key is silent in Python — `.get()` returns `None` — so neither failure ever raised.

1. **`has_premiere` was hardcoded-false by accident.** The tool mapped it to `SupportsAutoRunAtStartup`, a startup-service flag unrelated to licensing that is always `false` on Linux. Emby's `/System/Info` carries no licence field at all.
2. **`get_emby_connect_status` returned a row per user with every field null.** It ran `SELECT * FROM LocalUsersv2` against `users.db`, but that table is `(Id INTEGER, guid GUID, data BLOB)` — every user attribute is serialized inside the BLOB and unreachable by column name.

## Evidence (live Emby 4.9.5.0)

`/emby/System/Info` returns no licence and no path fields:

```json
{"ServerName": "Witflix", "Version": "4.9.5.0", "OperatingSystem": "Linux",
 "CanSelfRestart": true, "SupportsAutoRunAtStartup": false,
 "LocalAddresses": [], "RemoteAddresses": []}
```

`/emby/Plugins/SecurityInfo` is the actual licence source:

```json
{"SupporterKey": "479b5cab…", "IsMBSupporter": true}
```

`users.db` schema, confirming the BLOB:

```
PRAGMA table_info(LocalUsersv2) -> Id INTEGER | guid GUID | data BLOB
```

## Scope was wider than reported

The original report named one dead field in `get_server_info`. Five more had rotted the same way — Emby 4.9 dropped these keys from `/System/Info` entirely, so **6 of 12 fields were permanently null or false**:

| Field | Read | Reality in 4.9.5 |
|---|---|---|
| `has_premiere` | `SupportsAutoRunAtStartup` | unrelated flag; licence lives in `/Plugins/SecurityInfo` |
| `local_address` | `LocalAddress` | replaced by `LocalAddresses` (array) |
| `wan_address` | `WanAddress` | replaced by `RemoteAddresses` (array) |
| `program_data_path` | `ProgramDataPath` | absent |
| `items_by_name_path` | `ItemsByNamePath` | absent |
| `log_path` | `LogPath` | absent |
| `cache_path` | `CachePath` | absent |

`/System/Configuration` does expose `MetadataPath` and `CachePath`, but both are empty strings on a default install, so neither is a usable substitute.

## One half of the report did not reproduce

The report also claimed `get_emby_connect_status` returned **45 rows against a real count of 40**. It does not. Measured at investigation time, all three sources agreed on **40**:

- `SELECT COUNT(*) FROM LocalUsersv2` → 40
- `get_emby_connect_status` → `count: 40`
- REST `/emby/Users` → 40

`users.db` was not diverging from REST. The row `Id`s run 1–52 with gaps, which is an easy miscount by eye. Only the null-field half of that report was a real defect.

## Root cause

Schema and API drift across the Emby 4.9 upgrade, in the same class as the v1.3.0 `TypedBaseItems`/`PlaylistItems` table renames — but at *field* level rather than table level. Table rot is loud (`no such table`); field rot is silent.

## Fix

- `get_server_info` now reads Premiere status from `/emby/Plugins/SecurityInfo` (`IsMBSupporter`). When that call fails, `has_premiere` is `null` — unknown, never a confident `false`.
- Addresses now report the real `local_addresses` / `remote_addresses` arrays.
- The four unobtainable path fields are replaced by `config_path` / `db_path` / `log_path`, sourced from this server's own configuration — the paths its DB and log tools actually read.
- `get_emby_connect_status` is repointed to REST `/emby/Users`, which carries `Name`, GUID `Id`, `ConnectUserName`, `ConnectLinkType`, `HasPassword`, `HasConfiguredPassword` and the activity dates. It gains a `connect_linked` count. `connect_user_id` is dropped — Emby 4.9 exposes no such field, so it could only ever be null.

## Regression guard

`tests/test_no_dead_api_fields.py` is the field-level sibling of `test_no_dead_tables.py`: it fails if source code reads any API field Emby 4.9 does not return, or queries `LocalUsersv2` for attribute columns. It strips comments and docstrings before matching, so these names stay writable in prose that warns against them.
