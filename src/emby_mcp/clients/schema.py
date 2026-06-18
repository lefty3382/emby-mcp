"""Emby 4.9+ library.db schema names (renamed from the pre-4.9 schema).

Pre-4.9 -> 4.9+:
  - The old item table was renamed; see ITEMS_TABLE below.
  - The old playlist-membership table was renamed; see LIST_ITEMS_TABLE
    (PlaylistId -> ListId; adds ListItemId, ListItemOrder).
  - Owner-private sharing is recorded in USER_ITEM_SHARES_TABLE.

Centralizing these names keeps a future Emby rename to a one-line change.
"""

ITEMS_TABLE = "MediaItems"                 # was the pre-4.9 base-item table
LIST_ITEMS_TABLE = "ListItems"             # was the pre-4.9 playlist-items table
USER_ITEM_SHARES_TABLE = "UserItemShares"

PLAYLIST_TYPE = 16                         # MediaItems.type value for playlists
SHARE_LEVEL_PRIVATE = 10000                # UserItemShares.ShareLevel for owner-private
