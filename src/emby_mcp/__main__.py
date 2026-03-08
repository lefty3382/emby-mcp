"""Entry point for the Emby MCP server."""

import sys

from .config import AppConfig
from .clients.emby_client import EmbyClient
from .clients.emby_database import EmbyDatabase
from .server import create_server


def main() -> None:
    """Main entry point."""
    try:
        config = AppConfig.from_env()

        client = EmbyClient(config)
        database = EmbyDatabase(config)

        print(f"Emby API target: {config.emby_base_url}")
        print(f"Database path: {config.db_path}")

        mcp = create_server(config, client, database)

        mcp.run(
            transport="streamable-http",
            stateless_http=True,
            host="0.0.0.0",
            port=config.mcp_port,
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
