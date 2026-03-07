"""User & Session tools — CRUD, sessions, playback history."""

from fastmcp import FastMCP

from ..clients.emby_client import EmbyClient


def register_user_tools(mcp: FastMCP, client: EmbyClient) -> None:
    """Register user and session management tools."""

    @mcp.tool
    async def list_users() -> dict:
        """List all Emby users with basic info — name, ID, last login, admin status."""
        users = await client.get("/emby/Users")
        result = []
        for u in users:
            result.append({
                "id": u.get("Id"),
                "name": u.get("Name"),
                "last_login": u.get("LastLoginDate"),
                "last_activity": u.get("LastActivityDate"),
                "is_administrator": u.get("Policy", {}).get("IsAdministrator", False),
                "is_disabled": u.get("Policy", {}).get("IsDisabled", False),
                "has_password": u.get("HasPassword", False),
                "has_configured_password": u.get("HasConfiguredPassword", False),
            })
        return {"users": result, "count": len(result)}

    @mcp.tool
    async def get_user_details(user_id: str) -> dict:
        """Get full details for a specific user including policy and library access.

        Args:
            user_id: The Emby user ID.
        """
        user = await client.get(f"/emby/Users/{user_id}")
        return {
            "id": user.get("Id"),
            "name": user.get("Name"),
            "server_id": user.get("ServerId"),
            "connect_user_name": user.get("ConnectUserName"),
            "connect_link_type": user.get("ConnectLinkType"),
            "last_login": user.get("LastLoginDate"),
            "last_activity": user.get("LastActivityDate"),
            "has_password": user.get("HasPassword"),
            "has_configured_password": user.get("HasConfiguredPassword"),
            "policy": user.get("Policy", {}),
            "configuration": user.get("Configuration", {}),
        }

    @mcp.tool
    async def get_active_sessions() -> dict:
        """Get all active sessions with device, client, and playback info."""
        sessions = await client.get("/emby/Sessions")
        result = []
        for s in sessions:
            session = {
                "id": s.get("Id"),
                "user_name": s.get("UserName"),
                "user_id": s.get("UserId"),
                "device_name": s.get("DeviceName"),
                "device_id": s.get("DeviceId"),
                "client": s.get("Client"),
                "application_version": s.get("ApplicationVersion"),
                "last_activity": s.get("LastActivityDate"),
                "remote_end_point": s.get("RemoteEndPoint"),
                "is_active": s.get("IsActive"),
                "now_playing": None,
            }
            if s.get("NowPlayingItem"):
                item = s["NowPlayingItem"]
                session["now_playing"] = {
                    "name": item.get("Name"),
                    "type": item.get("Type"),
                    "series_name": item.get("SeriesName"),
                }
            result.append(session)
        return {"sessions": result, "count": len(result)}

    @mcp.tool
    async def get_playback_history(
        user_id: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Get playback history with timestamps.

        Args:
            user_id: Optional user ID to filter by. If omitted, returns all users.
            limit: Maximum items to return (default: 50).
        """
        params = {
            "IncludeItemTypes": "Movie,Episode",
            "IsPlayed": "true",
            "SortBy": "DatePlayed",
            "SortOrder": "Descending",
            "Limit": str(limit),
            "Recursive": "true",
            "Fields": "DateCreated,MediaSources",
        }
        if user_id:
            data = await client.get(f"/emby/Users/{user_id}/Items", params=params)
        else:
            # Get admin user to query all items
            users = await client.get("/emby/Users")
            admin = next(
                (u for u in users if u.get("Policy", {}).get("IsAdministrator")),
                users[0] if users else None,
            )
            if not admin:
                return {"error": "No users found"}
            data = await client.get(
                f"/emby/Users/{admin['Id']}/Items", params=params
            )

        items = []
        for item in data.get("Items", []):
            items.append({
                "name": item.get("Name"),
                "type": item.get("Type"),
                "series_name": item.get("SeriesName"),
                "date_played": item.get("UserData", {}).get("LastPlayedDate"),
                "play_count": item.get("UserData", {}).get("PlayCount", 0),
            })
        return {"history": items, "count": len(items)}

    @mcp.tool
    async def create_user(name: str) -> dict:
        """Create a new local Emby user account.

        Args:
            name: Display name for the new user.
        """
        result = await client.post("/emby/Users/New", data={"Name": name})
        return {
            "created": True,
            "id": result.get("Id"),
            "name": result.get("Name"),
        }

    @mcp.tool
    async def delete_user(user_id: str) -> dict:
        """Delete an Emby user account.

        Args:
            user_id: The Emby user ID to delete.
        """
        await client.post(f"/emby/Users/{user_id}/Delete")
        return {"deleted": True, "user_id": user_id}

    @mcp.tool
    async def reset_password(user_id: str, new_password: str = "") -> dict:
        """Reset a user's local password.

        Args:
            user_id: The Emby user ID.
            new_password: New password. Empty string removes the password.
        """
        # First reset to empty
        await client.post(
            f"/emby/Users/{user_id}/Password",
            data={"ResetPassword": True},
        )
        # Then set new password if provided
        if new_password:
            await client.post(
                f"/emby/Users/{user_id}/Password",
                data={"CurrentPw": "", "NewPw": new_password},
            )
        return {
            "reset": True,
            "user_id": user_id,
            "password_set": bool(new_password),
        }

    @mcp.tool
    async def set_library_access(
        user_id: str,
        enabled_folders: list[str] | None = None,
        enable_all: bool = False,
    ) -> dict:
        """Configure which libraries a user can access.

        Args:
            user_id: The Emby user ID.
            enabled_folders: List of library IDs to grant access to. Omit to keep current.
            enable_all: If true, grant access to all libraries.
        """
        user = await client.get(f"/emby/Users/{user_id}")
        policy = user.get("Policy", {})

        if enable_all:
            policy["EnableAllFolders"] = True
        elif enabled_folders is not None:
            policy["EnableAllFolders"] = False
            policy["EnabledFolders"] = enabled_folders

        await client.post(f"/emby/Users/{user_id}/Policy", data=policy)
        return {
            "updated": True,
            "user_id": user_id,
            "enable_all_folders": policy.get("EnableAllFolders"),
            "enabled_folders": policy.get("EnabledFolders", []),
        }

    @mcp.tool
    async def update_user(
        user_id: str,
        name: str | None = None,
        connect_user_name: str | None = None,
    ) -> dict:
        """Update user attributes — display name, Emby Connect email.

        Args:
            user_id: The Emby user ID.
            name: New display name. Omit to keep current.
            connect_user_name: Emby Connect email/username. Omit to keep current.
        """
        user = await client.get(f"/emby/Users/{user_id}")

        if name is not None:
            user["Name"] = name
        if connect_user_name is not None:
            user["ConnectUserName"] = connect_user_name

        await client.post(f"/emby/Users/{user_id}", data=user)
        return {
            "updated": True,
            "user_id": user_id,
            "name": user.get("Name"),
            "connect_user_name": user.get("ConnectUserName"),
        }
