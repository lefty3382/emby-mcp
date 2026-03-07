"""Application configuration from environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    """Emby MCP server configuration."""

    emby_host: str
    emby_port: int
    emby_api_key: str
    config_path: str
    mcp_port: int

    @property
    def emby_base_url(self) -> str:
        return f"http://{self.emby_host}:{self.emby_port}"

    @property
    def db_path(self) -> str:
        return os.path.join(self.config_path, "data")

    @property
    def log_path(self) -> str:
        return os.path.join(self.config_path, "logs")

    @classmethod
    def from_env(cls) -> "AppConfig":
        api_key = os.environ.get("EMBY_API_KEY", "")
        if not api_key:
            raise ValueError("EMBY_API_KEY environment variable is required")

        return cls(
            emby_host=os.environ.get("EMBY_HOST", "emby"),
            emby_port=int(os.environ.get("EMBY_PORT", "8096")),
            emby_api_key=api_key,
            config_path=os.environ.get("EMBY_CONFIG_PATH", "/emby-config"),
            mcp_port=int(os.environ.get("MCP_PORT", "8486")),
        )
