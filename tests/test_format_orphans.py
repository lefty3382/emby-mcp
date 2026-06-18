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
