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
