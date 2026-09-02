"""get_emby_connect_status shaping — Connect linkage read from REST /Users."""

from emby_mcp.tools.database_tools import _build_connect_status

# Shapes taken from a live Emby 4.9.5 /emby/Users response.
LINKED = {
    "Id": "a085474ae1a74094b0a9e5d8c35f242f",
    "Name": "AdminBackup",
    "ConnectUserName": "someone@example.com",
    "ConnectLinkType": "LinkedUser",
    "HasPassword": False,
    "HasConfiguredPassword": False,
    "LastActivityDate": "2026-03-13T00:39:50.1005550Z",
}
LOCAL_ONLY = {
    "Id": "d52c1aaaa8b0462780532848e35a1849",
    "Name": "Admin",
    "HasPassword": True,
    "HasConfiguredPassword": True,
    "LastLoginDate": "2026-07-14T03:30:43.2009556Z",
    "LastActivityDate": "2026-07-14T04:10:14.5080123Z",
}


def test_linked_user_keeps_its_connect_details():
    [row] = _build_connect_status([LINKED])
    assert row["id"] == "a085474ae1a74094b0a9e5d8c35f242f"
    assert row["name"] == "AdminBackup"
    assert row["connect_user_name"] == "someone@example.com"
    assert row["connect_link_type"] == "LinkedUser"
    assert row["last_activity_date"] == "2026-03-13T00:39:50.1005550Z"


def test_id_is_the_guid_not_an_internal_row_id():
    """LocalUsersv2.Id is an integer rowid; every other tool speaks GUIDs."""
    [row] = _build_connect_status([LINKED])
    assert row["id"] == LINKED["Id"]


def test_auth_method_connect_only():
    [row] = _build_connect_status([LINKED])
    assert row["auth_method"] == "connect"
    assert row["has_local_password"] is False


def test_auth_method_local_only():
    [row] = _build_connect_status([LOCAL_ONLY])
    assert row["auth_method"] == "local"
    assert row["has_local_password"] is True


def test_auth_method_connect_plus_local():
    user = {**LINKED, "HasConfiguredPassword": True}
    [row] = _build_connect_status([user])
    assert row["auth_method"] == "connect+local"


def test_auth_method_none_when_passwordless_and_unlinked():
    user = {"Id": "x", "Name": "Kiosk", "HasPassword": False,
            "HasConfiguredPassword": False}
    [row] = _build_connect_status([user])
    assert row["auth_method"] == "none"


def test_missing_last_login_stays_absent_not_invented():
    [row] = _build_connect_status([LINKED])
    assert row["last_login_date"] is None


def test_drops_connect_user_id_which_emby_4_9_does_not_expose():
    [row] = _build_connect_status([LINKED])
    assert "connect_user_id" not in row


def test_shapes_every_user_in_order():
    rows = _build_connect_status([LINKED, LOCAL_ONLY])
    assert [r["name"] for r in rows] == ["AdminBackup", "Admin"]
