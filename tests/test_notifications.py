"""
tests/test_notifications.py — Mixtape

Tests for notification creation, covering both add_to_playlist() and
rate_song().
"""

import pytest
from app import create_app, db
from models import User, Song, Playlist, playlist_entries
from services.notification_service import add_to_playlist, rate_song, get_notifications


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def sharer_and_rater(app):
    """A user who shares a song, and a separate user who will rate it."""
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="Golden Hour", artist="Someone", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()

        yield {"sharer": sharer, "rater": rater, "song": song}


def test_rating_a_song_notifies_the_sharer(app, sharer_and_rater):
    """
    Rating a song should notify the original sharer, the same way adding
    it to a playlist does. Bug: rate_song() saved the Rating row but never
    called create_notification(), so no notification was ever produced.
    """
    with app.app_context():
        sharer_id = sharer_and_rater["sharer"].id
        rater_id = sharer_and_rater["rater"].id
        song_id = sharer_and_rater["song"].id

        rate_song(rater_id, song_id, 5)

        notifications = get_notifications(sharer_id)
        assert len(notifications) == 1
        assert notifications[0]["type"] == "song_rated"
        assert "rater" in notifications[0]["body"]


def test_rating_your_own_song_does_not_notify_you(app, sharer_and_rater):
    """Self-rating should not create a spurious notification, mirroring add_to_playlist()'s self-add exemption."""
    with app.app_context():
        sharer_id = sharer_and_rater["sharer"].id
        song_id = sharer_and_rater["song"].id

        rate_song(sharer_id, song_id, 4)

        assert get_notifications(sharer_id) == []


def test_adding_to_playlist_still_notifies_the_sharer(app, sharer_and_rater):
    """
    Regression guard: the existing add_to_playlist() notification path must
    keep working after adding the rate_song() notification above it in the
    same file. The song is inserted into playlist_entries directly (as
    seed_data.py does) so this test only exercises the notification branch
    of add_to_playlist(), not its unrelated (and separately broken) use of
    the ORM relationship's .append() to insert playlist_entries rows.
    """
    with app.app_context():
        sharer = sharer_and_rater["sharer"]
        rater = sharer_and_rater["rater"]
        song = sharer_and_rater["song"]

        playlist = Playlist(name="Weekend Mix", created_by=rater.id)
        db.session.add(playlist)
        db.session.flush()

        db.session.execute(
            playlist_entries.insert().values(
                playlist_id=playlist.id,
                song_id=song.id,
                position=1,
                added_by=rater.id,
            )
        )
        db.session.commit()

        add_to_playlist(playlist.id, song.id, rater.id)

        notifications = get_notifications(sharer.id)
        assert len(notifications) == 1
        assert notifications[0]["type"] == "song_added_to_playlist"
