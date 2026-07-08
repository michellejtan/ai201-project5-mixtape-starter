"""
tests/test_feed.py — Mixtape

Tests for the "Friends Listening Now" feed logic.
"""

import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def friends(app):
    """Create two friended users and a song shared by the friend."""
    with app.app_context():
        me = User(username="me", email="me@example.com")
        friend = User(username="friend", email="friend@example.com")
        db.session.add_all([me, friend])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=me.id, friend_id=friend.id))
        db.session.execute(friendships.insert().values(user_id=friend.id, friend_id=me.id))

        song = Song(title="Late Night Session", artist="Someone", shared_by=friend.id)
        db.session.add(song)
        db.session.commit()

        yield {"me": me, "friend": friend, "song": song}


def _log_listen(friend_id, song_id, when):
    event = ListeningEvent(user_id=friend_id, song_id=song_id, listened_at=when)
    db.session.add(event)
    db.session.commit()


def test_friend_listening_2_hours_ago_is_not_shown(app, friends):
    """
    A friend who listened 2 hours ago should NOT appear as "listening now".
    Bug: RECENT_THRESHOLD was timedelta(hours=24), so anything from the last
    full day (including a stale 2-hour-old listen) was wrongly included.
    """
    with app.app_context():
        two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
        _log_listen(friends["friend"].id, friends["song"].id, two_hours_ago)

        result = get_friends_listening_now(friends["me"].id)
        assert result == []


def test_friend_listening_5_minutes_ago_is_shown(app, friends):
    """A friend who listened 5 minutes ago should appear as listening now."""
    with app.app_context():
        five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
        _log_listen(friends["friend"].id, friends["song"].id, five_min_ago)

        result = get_friends_listening_now(friends["me"].id)
        assert len(result) == 1
        assert result[0]["friend"]["username"] == "friend"


def test_no_friends_listening_returns_empty_list(app, friends):
    """A friend with no listening events at all should not appear."""
    with app.app_context():
        result = get_friends_listening_now(friends["me"].id)
        assert result == []
