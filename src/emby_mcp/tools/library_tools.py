"""Library tools — list, stats, scan."""

from fastmcp import FastMCP

from ..clients.emby_client import EmbyClient


def register_library_tools(mcp: FastMCP, client: EmbyClient) -> None:
    """Register library management tools."""

    @mcp.tool
    async def list_libraries() -> dict:
        """List all media libraries with type, path, and item count."""
        libraries = await client.get("/emby/Library/VirtualFolders")
        result = []
        for lib in libraries:
            result.append({
                "name": lib.get("Name"),
                "item_id": lib.get("ItemId"),
                "collection_type": lib.get("CollectionType"),
                "locations": lib.get("Locations", []),
                "refresh_status": lib.get("RefreshStatus"),
            })
        return {"libraries": result, "count": len(result)}

    @mcp.tool
    async def get_library_stats(library_id: str) -> dict:
        """Get detailed statistics for a specific library.

        Args:
            library_id: The library's ItemId (from list_libraries).
        """
        # Get admin user for querying
        users = await client.get("/emby/Users")
        admin = next(
            (u for u in users if u.get("Policy", {}).get("IsAdministrator")),
            users[0] if users else None,
        )
        if not admin:
            return {"error": "No users found"}

        # Get item counts by type
        item_types = ["Movie", "Series", "Episode", "Season"]
        stats = {"library_id": library_id, "by_type": {}}

        for item_type in item_types:
            data = await client.get(
                f"/emby/Users/{admin['Id']}/Items",
                params={
                    "ParentId": library_id,
                    "IncludeItemTypes": item_type,
                    "Recursive": "true",
                    "Limit": "0",
                },
            )
            stats["by_type"][item_type] = data.get("TotalRecordCount", 0)

        # Get total with some fields for overview
        data = await client.get(
            f"/emby/Users/{admin['Id']}/Items",
            params={
                "ParentId": library_id,
                "Recursive": "true",
                "Limit": "0",
            },
        )
        stats["total_items"] = data.get("TotalRecordCount", 0)

        return stats

    @mcp.tool
    async def scan_library(library_name: str | None = None) -> dict:
        """Trigger a library scan. Scans all libraries if no name specified.

        Args:
            library_name: Specific library name to scan. Omit to scan all.
        """
        if library_name is None:
            await client.post("/emby/Library/Refresh")
            return {"scanning": "all libraries"}

        libraries = await client.get("/emby/Library/VirtualFolders")
        library = next(
            (lib for lib in libraries if lib["Name"] == library_name), None
        )
        if not library:
            available = [lib["Name"] for lib in libraries]
            return {
                "error": f"Library '{library_name}' not found",
                "available_libraries": available,
            }

        await client.post(
            f"/emby/Items/{library['ItemId']}/Refresh",
            params={"Recursive": "true"},
        )
        return {"scanning": library_name, "library_id": library["ItemId"]}
