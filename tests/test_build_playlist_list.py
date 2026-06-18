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
