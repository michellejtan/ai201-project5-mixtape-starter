"""
services/search_service.py — Mixtape

Handles song search logic.
"""

from app import db
from models import Song


def search_songs(query: str) -> list[dict]:
    """
    Search for songs by title or artist name.

    Returns all songs where the title or artist contains the query string
    (case-insensitive), along with their associated tags.

    Args:
        query: The search string to match against title and artist fields.

    Returns:
        A list of song dicts. Each dict includes all song fields plus a
        'tags' list of tag name strings.
    """
    # Bug fix: this query used to outerjoin against song_tags even though
    # the filter never references it and tags are already loaded via the
    # Song.tags relationship (see to_dict()). Joining a many-to-many table
    # produces one row per matching tag, so any song with more than one tag
    # was fetched multiple times — the duplication only showed up
    # conditionally, once a song had 2+ tags. Dropping the unnecessary join
    # removes the row fanout entirely instead of relying on the join.
    # The song_tags join isn't needed for filtering (tags load via the
    # Song.tags relationship in to_dict()) and fans out one row per matching
    # tag, which silently breaks LIMIT/OFFSET pagination on multi-tag songs.
    results = (
        db.session.query(Song)
        # .outerjoin(song_tags, Song.id == song_tags.c.song_id)
        .filter(
            db.or_(
                Song.title.ilike(f"%{query}%"),
                Song.artist.ilike(f"%{query}%"),
            )
        )
        .all()
    )

    return [song.to_dict() for song in results]


def get_song(song_id: str) -> dict:
    """
    Get a single song by ID.

    Args:
        song_id: The UUID of the song.

    Returns:
        A song dict, or raises ValueError if not found.
    """
    song = db.session.get(Song, song_id)
    if not song:
        raise ValueError(f"Song {song_id} not found")
    return song.to_dict()
