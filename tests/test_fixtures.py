async def test_fixture_seeds_two_playlists(emby_db):
    rows = await emby_db.query(
        "library.db", "SELECT COUNT(*) AS c FROM MediaItems WHERE type = 16"
    )
    assert rows[0]["c"] == 2


def test_fixture_files_exist(data_dir):
    assert (data_dir / "library.db").exists()
    assert (data_dir / "users.db").exists()
