# Project 5: Mixtape Bug Hunt Submission

# Codebase Map

## Overview

Mixtape follows a layered architecture that separates HTTP request handling from business logic. The route modules receive HTTP requests, validate input, and return JSON responses, while the `services/` layer contains the application's business logic. Database persistence is handled through SQLAlchemy models defined in `models.py`. This organization makes it easier to trace bugs because most application behavior lives in the service layer rather than inside the routes.

## Main Files and Responsibilities

### `app.py`

- Implements the Flask application factory (`create_app()`).
- Configures the database connection and application settings.
- Initializes SQLAlchemy.
- Registers the application's blueprints:
  - `songs`
  - `playlists`
  - `users`
  - `feed`
- Creates database tables when the application starts.

### `models.py`

Defines all database models and relationships used by the application.

**Models**

- **User**
  - Stores account information, listening streaks, friendships, playlists, notifications, ratings, and listening history.
- **Song**
  - Stores song metadata, the user who shared the song, ratings, listening events, and tags.
- **ListeningEvent**
  - Records when a user listens to a song.
- **Rating**
  - Stores a user's 1–5 rating for a song.
  - Prevents duplicate ratings through a unique constraint on `(user_id, song_id)`.
- **Playlist**
  - Stores collaborative playlists and their associated songs.
- **Notification**
  - Stores notifications sent to users.
- **Tag**
  - Stores tags that can be associated with songs.

**Association Tables**

- `friendships`
  - Many-to-many relationship between users.
- `song_tags`
  - Many-to-many relationship between songs and tags.
- `playlist_entries`
  - Many-to-many relationship between playlists and songs.
  - Also stores:
    - song position
    - who added the song
    - when it was added

### `routes/`

Routes are responsible for:

- Receiving HTTP requests
- Validating request data
- Calling the appropriate service function
- Returning JSON responses

The project contains four route modules:

- `songs.py`
- `playlists.py`
- `users.py`
- `feed.py`

### `services/`

Business logic is separated by feature into individual service modules:

- `streak_service.py`
  - Listening streak calculations
- `feed_service.py`
  - Friends Listening Now feed
- `search_service.py`
  - Song searching
- `notification_service.py`
  - Creating and retrieving notifications
- `playlist_service.py`
  - Playlist retrieval and ordering

---

# Data Flow Example

### Rating a Song

1. A client sends a `POST /songs/<song_id>/rate` request.
2. `routes/songs.py` validates that both `user_id` and `score` are present.
3. The route calls `rate_song()` from `notification_service.py`.
4. The service performs the rating logic, interacts with the SQLAlchemy models, creates any necessary notifications, and returns the result.
5. The route converts the returned object to JSON using `to_dict()` and sends the HTTP response back to the client.

Another example of this pattern is the listening endpoint:

- `POST /songs/<song_id>/listen`
- validates the request
- calls `record_listening_event()` in `streak_service.py`
- the service records the listening event and updates the user's listening streak before returning the new event.

---

# Design Patterns Observed

While exploring the project, I noticed several consistent architectural patterns:

- The application uses the Flask application factory pattern (`create_app()`).
- SQLAlchemy models represent all persistent data.
- Business logic is intentionally separated from the route handlers.
- Routes mainly perform validation and delegate work to service functions.
- Services are organized by feature rather than by model.
- SQLAlchemy relationships are used extensively instead of manually writing joins.
- UUIDs are used as primary keys for all major entities.
- Several many-to-many relationships are implemented using association tables, with `playlist_entries` storing additional metadata beyond the relationship itself.

---
# Bug Fix 1

## Issue

Issue #1: "My listening streak keeps resetting." A user's listening streak
resets to 1 even when they listened on consecutive calendar days, if the
second day happens to be a Sunday.

## How I Reproduced It

In `services/streak_service.py`, `update_listening_streak()` has:

```python
elif days_since_last == 1 and today.weekday() != 6:
    user.listening_streak += 1
else:
    user.listening_streak = 1
```

The streak only increments when exactly one day has passed **and** today is
not a Sunday (`weekday() == 6`). So a genuinely consecutive-day listen that
lands on a Sunday falls through to the `else` branch and gets reset instead
of incremented.

To trigger it, I called `update_listening_streak()` directly with a `User`
whose `listening_streak = 5` and `last_listened_at` set to a Saturday, then
passed `now` as the following day (a Sunday, `2026-07-05`) — a true
one-day gap. Expected: streak becomes 6. Actual: streak resets to 1.

```
Before: streak=5, last_listened=2026-07-04 12:00:00+00:00
'today' is a Sunday, exactly 1 day since last listen (a real consecutive day)
After:  streak=1
BUG REPRODUCED: expected streak=6 (consecutive day), got 1
```

reproduce in flask shell
from datetime import datetime, timezone
from models import User, db
from services.streak_service import update_listening_streak
>>> for user in User.query.all():
...     print(user.username, user.listening_streak, user.last_listened_at)
... 
result:
nova 7 2026-07-06 03:09:45.653758
darius 3 2026-07-05 04:09:45.653758
simone 0 None
kenji 12 2026-07-06 01:09:45.653758
aaliya 1 None

new_time = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc) #Sunday, 07/12
users = User.query.all()

for user in users:
    update_listening_streak(user, new_time)


for user in User.query.all():
    print(user.username, user.listening_streak, user.last_listened_at)
result:
nova 1 2026-07-12 12:00:00+00:00
darius 1 2026-07-12 12:00:00+00:00
simone 1 2026-07-12 12:00:00+00:00
kenji 1 2026-07-12 12:00:00+00:00
aaliya 1 2026-07-12 12:00:00+00:00

## How I Found the Root Cause

Files examined: `routes/users.py` (to confirm the listen endpoint calls
`record_listening_event()`), then `services/streak_service.py`. I read
`update_listening_streak()` top-down: it computes `days_since_last` from
`last_listened_at` and `now`, then branches on that value. The moment I
saw the `elif` condition had a *second* clause (`and today.weekday() !=
6`) unrelated to `days_since_last`, that was the specific line — not just
"the streak logic" broadly, but that exact boolean AND — since nothing in
the module docstring or the rest of the function referenced weekday at
all.

## Root Cause

`update_listening_streak()` in `services/streak_service.py` computes
`days_since_last`, the calendar-day gap between `last_listened_at` and
`now`, and only increments the streak when that gap is exactly 1 **and**
`today.weekday() != 6`. `datetime.weekday()` returns `6` for Sunday, so
this second condition is false every time "today" is a Sunday — regardless
of how many days have actually passed since the last listen. The intent
of the streak logic (per the module docstring: "increments when a user
listens on consecutive calendar days") only depends on `days_since_last`;
the weekday check is an unrelated condition that was accidentally ANDed
into the consecutive-day branch, so any listen that happened to fall on a
Sunday — even a perfectly consecutive one — fell through to the `else`
branch and reset the streak to 1.

## Fix

Removed the `and today.weekday() != 6` clause from the `elif
days_since_last == 1:` branch in `services/streak_service.py`, so streak
continuation depends solely on `days_since_last == 1`.

## Verification

Re-ran the reproduction case (Saturday → Sunday, one real day apart):
streak now correctly goes from 5 to 6 instead of resetting to 1. I also
checked both sides of the boundary and the other branch directly:
- Consecutive-day listen landing on a non-Sunday (Monday → Tuesday):
  streak 5 → 6 (unaffected by the fix, confirms no regression).
- Gap of 4 days (still hits the `else` branch): streak resets to 1 as
  expected, so the actual reset behavior for skipped days is untouched.
- Full `pytest tests/` suite (13 tests) still passes.

## Commit

`fix: remove Sunday weekday check from streak increment condition`

---
