"""Playlist & Collection tools — list, create, add items, collections."""

from fastmcp import FastMCP

from ..clients.emby_client import EmbyClient


def register_playlist_tools(mcp: FastMCP, client: EmbyClient) -> None:
    """Register playlist and collection management tools."""

    @mcp.tool
    async def list_playlists() -> dict:
        """List all playlists with owner and item count."""
        users = await client.get("/emby/Users")
        admin = next(
            (u for u in users if u.get("Policy", {}).get("IsAdministrator")),
            users[0] if users else None,
        )
        if not admin:
            return {"error": "No users found"}

        data = await client.get(
            f"/emby/Users/{admin['Id']}/Items",
            params={
                "IncludeItemTypes": "Playlist",
                "Recursive": "true",
                "Fields": "ChildCount,Path",
            },
        )
        playlists = []
        for item in data.get("Items", []):
            playlists.append({
                "id": item.get("Id"),
                "name": item.get("Name"),
                "item_count": item.get("ChildCount", 0),
                "media_type": item.get("MediaType"),
                "path": item.get("Path"),
                "date_created": item.get("DateCreated"),
            })
        return {"playlists": playlists, "count": len(playlists)}

    @mcp.tool
    async def get_playlist_items(
        playlist_id: str,
        limit: int = 200,
    ) -> dict:
        """Get all items in a playlist.

        Args:
            playlist_id: The playlist ID.
            limit: Maximum items to return (default: 200).
        """
        data = await client.get(
            f"/emby/Playlists/{playlist_id}/Items",
            params={
                "Limit": str(limit),
                "Fields": "Path,MediaSources",
            },
        )
        items = []
        for item in data.get("Items", []):
            items.append({
                "id": item.get("Id"),
                "playlist_item_id": item.get("PlaylistItemId"),
                "name": item.get("Name"),
                "type": item.get("Type"),
                "year": item.get("ProductionYear"),
                "series_name": item.get("SeriesName"),
                "path": item.get("Path"),
            })
        return {
            "playlist_id": playlist_id,
            "items": items,
            "total": data.get("TotalRecordCount", len(items)),
        }

    @mcp.tool
    async def create_playlist(
        name: str,
        item_ids: list[str] | None = None,
        media_type: str = "Video",
    ) -> dict:
        """Create a new playlist.

        Args:
            name: Playlist name.
            item_ids: Optional list of item IDs to add initially.
            media_type: Media type — 'Video' or 'Audio' (default: 'Video').
        """
        # Get admin user ID for ownership
        users = await client.get("/emby/Users")
        admin = next(
            (u for u in users if u.get("Policy", {}).get("IsAdministrator")),
            users[0] if users else None,
        )
        if not admin:
            return {"error": "No users found"}

        params = {
            "Name": name,
            "UserId": admin["Id"],
            "MediaType": media_type,
        }
        if item_ids:
            params["Ids"] = ",".join(item_ids)

        result = await client.post("/emby/Playlists", params=params)
        return {
            "created": True,
            "id": result.get("Id"),
            "name": name,
            "initial_items": len(item_ids) if item_ids else 0,
        }

    @mcp.tool
    async def add_playlist_items(
        playlist_id: str,
        item_ids: list[str],
    ) -> dict:
        """Add items to an existing playlist.

        Args:
            playlist_id: The playlist ID.
            item_ids: List of item IDs to add.
        """
        await client.post(
            f"/emby/Playlists/{playlist_id}/Items",
            params={"Ids": ",".join(item_ids)},
        )
        return {
            "added": True,
            "playlist_id": playlist_id,
            "items_added": len(item_ids),
        }

    @mcp.tool
    async def list_collections() -> dict:
        """List all collections with item counts."""
        users = await client.get("/emby/Users")
        admin = next(
            (u for u in users if u.get("Policy", {}).get("IsAdministrator")),
            users[0] if users else None,
        )
        if not admin:
            return {"error": "No users found"}

        data = await client.get(
            f"/emby/Users/{admin['Id']}/Items",
            params={
                "IncludeItemTypes": "BoxSet",
                "Recursive": "true",
                "Fields": "ChildCount,Overview",
            },
        )
        collections = []
        for item in data.get("Items", []):
            collections.append({
                "id": item.get("Id"),
                "name": item.get("Name"),
                "item_count": item.get("ChildCount", 0),
                "overview": (item.get("Overview") or "")[:200],
                "date_created": item.get("DateCreated"),
            })
        return {"collections": collections, "count": len(collections)}
