async def test_guid_map_resolves_known_user(emby_db):
    mapping = await emby_db.get_internal_user_guid_map()
    assert mapping == {2: "db043bd8cb0a49b5b693dc3eceda6c17"}
