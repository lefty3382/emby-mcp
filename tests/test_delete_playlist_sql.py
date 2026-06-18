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
