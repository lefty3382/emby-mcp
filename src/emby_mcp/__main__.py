"""Entry point for the Emby MCP server."""

import asyncio
import sys

from .config import AppConfig
from .clients.emby_client import EmbyClient
from .clients.emby_database import EmbyDatabase
from .server import create_server


async def _startup() -> None:
    """Initialize clients and start the MCP server."""
    config = AppConfig.from_env()

    client = EmbyClient(config)
    await client.connect()
    print(f"Connected to Emby at {config.emby_base_url}")

    database = EmbyDatabase(config)
    print(f"Database path: {config.db_path}")

    mcp = create_server(config, client, database)

    try:
        mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=config.mcp_port,
        )
    finally:
        await client.disconnect()


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(_startup())
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
