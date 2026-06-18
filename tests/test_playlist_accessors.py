"""Tests for EmbyDatabase playlist read accessors."""

import pytest


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
