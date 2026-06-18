from emby_mcp.clients import schema


def test_schema_constants():
    assert schema.ITEMS_TABLE == "MediaItems"
    assert schema.LIST_ITEMS_TABLE == "ListItems"
    assert schema.USER_ITEM_SHARES_TABLE == "UserItemShares"
    assert schema.PLAYLIST_TYPE == 16
    assert schema.SHARE_LEVEL_PRIVATE == 10000
