"""Playlist & Collection tools — list, create, add items, collections."""

from fastmcp import FastMCP

from ..clients.emby_client import EmbyClient
from ..clients.emby_database import EmbyDatabase


def _build_playlist_list(
    rows: list[dict],
    id_to_guid: dict[int, str],
    rest_users: list[dict],
) -> list[dict]:
    """Shape DB playlist rows into tool output, resolving owner names.

    Args:
        rows: rows from EmbyDatabase.get_playlists().
        id_to_guid: {internal_user_id: 32-char guid} from get_internal_user_guid_map().
        rest_users: /emby/Users payload (each item has a 'Id' guid and 'Name').
    """
    guid_to_name = {(u.get("Id") or "").lower(): u.get("Name") for u in rest_users}
    playlists = []
    for row in rows:
        owner_id = row.get("owner_user_id")
        guid = id_to_guid.get(owner_id) if owner_id is not None else None
        playlists.append({
            "id": str(row.get("Id")),
            "name": row.get("Name"),
            "owner": guid_to_name.get(guid) if guid else None,
            "owner_user_id": owner_id,
            "item_count": row.get("item_count", 0),
            "path": row.get("Path"),
            "shared": owner_id is None,
        })
    return playlists


def register_playlist_tools(
    mcp: FastMCP, client: EmbyClient, database: EmbyDatabase
) -> None:
    """Register playlist and collection management tools."""

    @mcp.tool
    async def list_playlists() -> dict:
        """List all playlists (shared and owner-private) with owner and item count.

        Enumerated directly from library.db so owner-private playlists (invisible
        to the admin's user-scoped REST view) are included.
        """
        rows = await database.get_playlists()
        id_to_guid = await database.get_internal_user_guid_map()
        rest_users = await client.get("/emby/Users")
        playlists = _build_playlist_list(rows, id_to_guid, rest_users)
        return {"playlists": playlists, "count": len(playlists)}

    @mcp.tool
    async def get_playlist_items(
        playlist_id: str,
        limit: int = 200,
    ) -> dict:
        """Get all items in a playlist (works for owner-private playlists too).

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
