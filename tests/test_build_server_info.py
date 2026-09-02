"""get_server_info shaping — premiere status and Emby 4.9 field availability."""

import pytest

from emby_mcp.config import AppConfig
from emby_mcp.tools.server_tools import _build_server_info

# Trimmed to the fields Emby 4.9.5 actually returns from /System/Info.
SYSTEM_INFO = {
    "ServerName": "Witflix",
    "Version": "4.9.5.0",
    "OperatingSystem": "Linux",
    "Id": "87535ae1e5e643ce8f7aa327733deb9d",
    "CanSelfRestart": True,
    "SupportsAutoRunAtStartup": False,
    "LocalAddresses": ["http://10.0.40.20:8096"],
    "RemoteAddresses": ["https://wan.example:8920"],
}


@pytest.fixture
def config(tmp_path):
    return AppConfig(
        emby_host="emby",
        emby_port=8096,
        emby_api_key="k",
        config_path=str(tmp_path / "emby-config"),
        mcp_port=8486,
    )


def test_premiere_true_comes_from_security_info(config):
    out = _build_server_info(SYSTEM_INFO, {"IsMBSupporter": True}, config)
    assert out["has_premiere"] is True


def test_premiere_false_when_not_a_supporter(config):
    out = _build_server_info(SYSTEM_INFO, {"IsMBSupporter": False}, config)
    assert out["has_premiere"] is False


def test_premiere_unknown_when_security_info_unavailable(config):
    """A failed SecurityInfo call must not masquerade as 'no Premiere'."""
    out = _build_server_info(SYSTEM_INFO, None, config)
    assert out["has_premiere"] is None


def test_premiere_ignores_supports_auto_run_at_startup(config):
    """SupportsAutoRunAtStartup is a startup-service flag, not a licence flag."""
    info = {**SYSTEM_INFO, "SupportsAutoRunAtStartup": True}
    out = _build_server_info(info, {"IsMBSupporter": False}, config)
    assert out["has_premiere"] is False


def test_addresses_use_the_4_9_array_fields(config):
    out = _build_server_info(SYSTEM_INFO, {"IsMBSupporter": True}, config)
    assert out["local_addresses"] == ["http://10.0.40.20:8096"]
    assert out["remote_addresses"] == ["https://wan.example:8920"]


def test_addresses_default_to_empty_lists(config):
    out = _build_server_info({}, {}, config)
    assert out["local_addresses"] == []
    assert out["remote_addresses"] == []


def test_paths_come_from_config_not_from_system_info(config):
    """Emby 4.9 stopped returning ProgramDataPath/LogPath/CachePath."""
    out = _build_server_info(SYSTEM_INFO, {"IsMBSupporter": True}, config)
    assert out["config_path"] == config.config_path
    assert out["db_path"] == config.db_path
    assert out["log_path"] == config.log_path


def test_no_field_is_sourced_from_an_absent_system_info_key(config):
    """Every reported key must have a real source — no permanent nulls."""
    out = _build_server_info(SYSTEM_INFO, {"IsMBSupporter": True}, config)
    for dead in ("program_data_path", "items_by_name_path", "cache_path",
                 "local_address", "wan_address"):
        assert dead not in out
