"""Item & Search tools — movies, series, seasons, episodes, search."""

from fastmcp import FastMCP

from ..clients.emby_client import EmbyClient


def _get_admin_id_coro(client: EmbyClient):
    """Helper to get admin user ID for item queries."""
    async def _get():
        users = await client.get("/emby/Users")
        admin = next(
            (u for u in users if u.get("Policy", {}).get("IsAdministrator")),
            users[0] if users else None,
        )
        if not admin:
            raise RuntimeError("No users found")
        return admin["Id"]
    return _get


def register_item_tools(mcp: FastMCP, client: EmbyClient) -> None:
    """Register item browsing and search tools."""

    _admin_id = _get_admin_id_coro(client)

    @mcp.tool
    async def search_items(
        query: str,
        item_type: str | None = None,
        limit: int = 25,
    ) -> dict:
        """Search for items by name across all libraries.

        Args:
            query: Search text.
            item_type: Optional type filter — 'Movie', 'Series', 'Episode', 'Audio', etc.
            limit: Maximum results (default: 25).
        """
        admin_id = await _admin_id()
        params = {
            "SearchTerm": query,
            "Recursive": "true",
            "Limit": str(limit),
            "Fields": "Path,MediaSources,Overview",
        }
        if item_type:
            params["IncludeItemTypes"] = item_type

        data = await client.get(f"/emby/Users/{admin_id}/Items", params=params)
        items = []
        for item in data.get("Items", []):
            items.append({
                "id": item.get("Id"),
                "name": item.get("Name"),
                "type": item.get("Type"),
                "year": item.get("ProductionYear"),
                "series_name": item.get("SeriesName"),
                "path": item.get("Path"),
                "overview": (item.get("Overview") or "")[:200],
            })
        return {
            "results": items,
            "total": data.get("TotalRecordCount", len(items)),
            "query": query,
        }

    @mcp.tool
    async def get_item_details(item_id: str) -> dict:
        """Get full metadata for a specific item.

        Args:
            item_id: The Emby item ID.
        """
        admin_id = await _admin_id()
        item = await client.get(
            f"/emby/Users/{admin_id}/Items/{item_id}",
            params={"Fields": "Path,MediaSources,Overview,People,Studios,Genres"},
        )
        result = {
            "id": item.get("Id"),
            "name": item.get("Name"),
            "type": item.get("Type"),
            "year": item.get("ProductionYear"),
            "overview": item.get("Overview"),
            "path": item.get("Path"),
            "community_rating": item.get("CommunityRating"),
            "official_rating": item.get("OfficialRating"),
            "genres": item.get("Genres", []),
            "studios": [s.get("Name") for s in item.get("Studios", [])],
            "series_name": item.get("SeriesName"),
            "season_name": item.get("SeasonName"),
            "index_number": item.get("IndexNumber"),
            "parent_index_number": item.get("ParentIndexNumber"),
            "premiere_date": item.get("PremiereDate"),
            "date_created": item.get("DateCreated"),
        }

        # Add media source info if available
        sources = item.get("MediaSources", [])
        if sources:
            src = sources[0]
            result["media_info"] = {
                "container": src.get("Container"),
                "size_bytes": src.get("Size"),
                "bitrate": src.get("Bitrate"),
                "path": src.get("Path"),
            }
            # Video stream
            for stream in src.get("MediaStreams", []):
                if stream.get("Type") == "Video":
                    result["media_info"]["video"] = {
                        "codec": stream.get("Codec"),
                        "width": stream.get("Width"),
                        "height": stream.get("Height"),
                        "bit_depth": stream.get("BitDepth"),
                        "is_avc": stream.get("IsAVC"),
                    }
                    break

        return result

    @mcp.tool
    async def get_recently_added(
        library_id: str | None = None,
        item_type: str | None = None,
        limit: int = 25,
    ) -> dict:
        """Get recently added items.

        Args:
            library_id: Optional library ID to filter by.
            item_type: Optional type — 'Movie', 'Series', 'Episode'.
            limit: Maximum results (default: 25).
        """
        admin_id = await _admin_id()
        params = {
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "Recursive": "true",
            "Limit": str(limit),
            "Fields": "Path,DateCreated",
        }
        if library_id:
            params["ParentId"] = library_id
        if item_type:
            params["IncludeItemTypes"] = item_type

        data = await client.get(f"/emby/Users/{admin_id}/Items", params=params)
        items = []
        for item in data.get("Items", []):
            items.append({
                "id": item.get("Id"),
                "name": item.get("Name"),
                "type": item.get("Type"),
                "year": item.get("ProductionYear"),
                "series_name": item.get("SeriesName"),
                "date_added": item.get("DateCreated"),
                "path": item.get("Path"),
            })
        return {"items": items, "count": len(items)}

    @mcp.tool
    async def get_movies(
        sort_by: str = "SortName",
        sort_order: str = "Ascending",
        genre: str | None = None,
        year: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Browse and filter movies.

        Args:
            sort_by: Sort field — 'SortName', 'DateCreated', 'CommunityRating', 'ProductionYear'.
            sort_order: 'Ascending' or 'Descending'.
            genre: Optional genre filter.
            year: Optional year filter.
            limit: Maximum results (default: 50).
            offset: Pagination offset (default: 0).
        """
        admin_id = await _admin_id()
        params = {
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "SortBy": sort_by,
            "SortOrder": sort_order,
            "Limit": str(limit),
            "StartIndex": str(offset),
            "Fields": "Path,MediaSources,Genres",
        }
        if genre:
            params["Genres"] = genre
        if year:
            params["Years"] = str(year)

        data = await client.get(f"/emby/Users/{admin_id}/Items", params=params)
        items = []
        for item in data.get("Items", []):
            entry = {
                "id": item.get("Id"),
                "name": item.get("Name"),
                "year": item.get("ProductionYear"),
                "rating": item.get("CommunityRating"),
                "genres": item.get("Genres", []),
                "path": item.get("Path"),
            }
            sources = item.get("MediaSources", [])
            if sources:
                src = sources[0]
                for stream in src.get("MediaStreams", []):
                    if stream.get("Type") == "Video":
                        entry["video_codec"] = stream.get("Codec")
                        entry["resolution"] = f"{stream.get('Width')}x{stream.get('Height')}"
                        break
            items.append(entry)
        return {
            "movies": items,
            "total": data.get("TotalRecordCount", len(items)),
            "offset": offset,
            "limit": limit,
        }

    @mcp.tool
    async def get_series(
        sort_by: str = "SortName",
        sort_order: str = "Ascending",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Browse and filter TV series.

        Args:
            sort_by: Sort field — 'SortName', 'DateCreated', 'CommunityRating'.
            sort_order: 'Ascending' or 'Descending'.
            limit: Maximum results (default: 50).
            offset: Pagination offset (default: 0).
        """
        admin_id = await _admin_id()
        params = {
            "IncludeItemTypes": "Series",
            "Recursive": "true",
            "SortBy": sort_by,
            "SortOrder": sort_order,
            "Limit": str(limit),
            "StartIndex": str(offset),
            "Fields": "Path,Overview",
        }

        data = await client.get(f"/emby/Users/{admin_id}/Items", params=params)
        items = []
        for item in data.get("Items", []):
            items.append({
                "id": item.get("Id"),
                "name": item.get("Name"),
                "year": item.get("ProductionYear"),
                "status": item.get("Status"),
                "rating": item.get("CommunityRating"),
                "overview": (item.get("Overview") or "")[:200],
                "path": item.get("Path"),
            })
        return {
            "series": items,
            "total": data.get("TotalRecordCount", len(items)),
            "offset": offset,
            "limit": limit,
        }

    @mcp.tool
    async def get_seasons(series_id: str) -> dict:
        """Get all seasons for a TV series.

        Args:
            series_id: The Emby series ID.
        """
        admin_id = await _admin_id()
        data = await client.get(
            f"/emby/Shows/{series_id}/Seasons",
            params={"UserId": admin_id},
        )
        seasons = []
        for item in data.get("Items", []):
            seasons.append({
                "id": item.get("Id"),
                "name": item.get("Name"),
                "index_number": item.get("IndexNumber"),
                "episode_count": item.get("ChildCount"),
                "year": item.get("ProductionYear"),
            })
        return {"series_id": series_id, "seasons": seasons, "count": len(seasons)}

    @mcp.tool
    async def get_episodes(
        series_id: str,
        season_number: int | None = None,
        limit: int = 100,
    ) -> dict:
        """Get episodes for a TV series, optionally filtered by season.

        Args:
            series_id: The Emby series ID.
            season_number: Optional season number to filter by.
            limit: Maximum results (default: 100).
        """
        admin_id = await _admin_id()
        params = {
            "UserId": admin_id,
            "Limit": str(limit),
            "Fields": "Path,MediaSources,Overview",
        }
        if season_number is not None:
            params["Season"] = str(season_number)

        data = await client.get(
            f"/emby/Shows/{series_id}/Episodes", params=params
        )
        episodes = []
        for item in data.get("Items", []):
            episodes.append({
                "id": item.get("Id"),
                "name": item.get("Name"),
                "season_number": item.get("ParentIndexNumber"),
                "episode_number": item.get("IndexNumber"),
                "overview": (item.get("Overview") or "")[:200],
                "path": item.get("Path"),
                "premiere_date": item.get("PremiereDate"),
            })
        return {
            "series_id": series_id,
            "season_filter": season_number,
            "episodes": episodes,
            "total": data.get("TotalRecordCount", len(episodes)),
        }
