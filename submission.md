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
# Investigation Note: Issue #3, First Pass

I initially attempted to reproduce Issue #3 ("the same song keeps showing
up twice in search"). `search_service.search_songs()` does an `outerjoin`
against the `song_tags` association table without ever using it in the
filter — the suspected bug is that joining a many-to-many table fans out
one row per matching tag, so a song with 2+ tags would be fetched multiple
times.

However, running the existing `tests/test_search.py` against the
unmodified (still-joined) service function shows all 5 tests passing,
including the ones written specifically to catch the duplicate. I also
reproduced this directly: a song with 3 tags returned exactly 1 result
from `search_songs()`, not 3. This is because SQLAlchemy 2.0's legacy
`Query` API auto-deduplicates full-entity results by primary key even when
the underlying SQL join fans out rows (confirmed the raw SQL join does
return 3 rows; the ORM layer collapses them to 1 before `to_dict()` is
called). At this point I could not trigger the reported behavior through
`search_songs()` as it's currently called, so I moved on to the other
issues rather than get stuck — see **Bug Fix 3** below for the follow-up
that found a real, if currently latent, defect behind this join.

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
# Bug Fix 2

## Issue

Issue #2: "Friends Listening Now shows people from yesterday." The
"listening now" feed is supposed to show friends who are currently
listening, but it kept surfacing friends who had listened at any point in
the last 24 hours.

## How I Reproduced It

`routes/feed.py` calls `get_friends_listening_now()` in
`services/feed_service.py`. That function builds a `cutoff` timestamp as
`datetime.now(timezone.utc) - RECENT_THRESHOLD` and only includes
`ListeningEvent`s at or after `cutoff`. `RECENT_THRESHOLD` was defined at
the top of the file as `timedelta(hours=24)`.

To trigger it, I created a `me`/`friend` pair, recorded a `ListeningEvent`
for `friend` timestamped 2 hours in the past (clearly not "right now" by
any reasonable definition of a listening session), and called
`get_friends_listening_now(me.id)`. Expected: an empty list, since the
friend isn't listening now. Actual: the friend showed up in the result,
because 2 hours is well inside a 24-hour window.

```
Friend listened 2h ago -> shown as listening now: True
BUG REPRODUCED: a friend who listened hours ago is shown as listening "now"
```

## How I Found the Root Cause

I started at `routes/feed.py`, traced the "listening now" endpoint to
`get_friends_listening_now()` in `services/feed_service.py`, and read the
query top-down: it filters `ListeningEvent.listened_at >= cutoff` where
`cutoff = now - RECENT_THRESHOLD`. The filter logic and dedup-by-friend
loop below it were both correct — the only place "now" was defined was the
`RECENT_THRESHOLD` constant itself, set to `timedelta(hours=24)`. A feed
named "Listening Now" using a 24-hour window is the mismatch: the query
logic isn't buggy, the threshold value it's built on is just far too wide
for what the feature is supposed to mean.

## The Root Cause

`RECENT_THRESHOLD` in `services/feed_service.py` was set to
`timedelta(hours=24)`. Any friend who had listened to anything at any
point in the last full day — not just "right now" — passed the
`listened_at >= cutoff` filter and was shown in the "Friends Listening
Now" feed. There was no logic bug in the filtering or dedup code; the
threshold constant itself just didn't match the feature's intent.

## Fix and Side-Effect Check

Changed `RECENT_THRESHOLD` from `timedelta(hours=24)` to
`timedelta(minutes=30)` in `services/feed_service.py`, so the feed only
reflects genuinely recent (session-scale) listening activity.

I checked `get_activity_feed()` in the same file, since it also queries
`ListeningEvent` for friends — it doesn't reference `RECENT_THRESHOLD` at
all (its docstring explicitly says it's "not filtered by recency"), so it
is unaffected by this change. I verified both sides of the new boundary:
a friend who listened 2 hours ago is now correctly excluded, and a friend
who listened 5 minutes ago is still correctly included.

## Verification

```
Friend listened 2h ago -> shown as listening now: False (expect False)
Friend listened 5min ago -> shown as listening now: True (expect True)
```

Full `pytest tests/` suite (13 tests) still passes.

## Commit

`fix: shrink Friends Listening Now window from 24h to 30min`

---
# Bug Fix 3

## Issue

Issue #3: "The same song keeps showing up twice in search." As noted in
the investigation note above, this couldn't be reproduced through the
current call path — but a real defect was still present in the query.

## How I Reproduced It

The first-pass reproduction attempt (see the investigation note) showed
that `search_songs()`, called plainly with no `LIMIT`/`OFFSET`, returns
exactly one result per song regardless of tag count, because SQLAlchemy's
legacy `Query` API deduplicates full-entity results by primary key even
when the underlying SQL fans out multiple rows per song.

To find a case where that auto-dedup doesn't save you, I simulated adding
pagination (`.limit(2)`) to the same query, which is a realistic future
change for a search endpoint. With the `outerjoin` against `song_tags`
still in place, `LIMIT` is applied by the database to the raw (fanned-out)
SQL rows *before* the ORM collapses duplicates in Python — so a single
multi-tag song can consume more than one row of the limit budget:

```
With outerjoin + limit(2):    ['Crown Heights Anthem']
Without outerjoin + limit(2): ['Crown Heights Anthem', 'Zzz Other']
```

A 3-tag song alone filled the 2-row limit, so a second, genuinely
different song ("Zzz Other") that should have appeared in the results was
silently dropped — this reproduces the family of bug the issue describes
(a multi-tag song distorting how many "slots" a song search actually
returns), just via pagination instead of a bare `.all()`.

## How I Found the Root Cause

Files examined: `services/search_service.py` (the query itself) and
`tests/test_search.py` (to see what behavior was already specified).
`search_songs()` builds `db.session.query(Song).outerjoin(song_tags, ...)`
but the `.filter()` right below it only references `Song.title` and
`Song.artist` — `song_tags` is never used in the `WHERE` clause. Checking
`Song.to_dict()` confirmed tags are already loaded through the
`Song.tags` relationship, so the join wasn't needed to build the response
either. The moment I applied `.limit()` to both the joined and un-joined
versions of the query side-by-side and saw the row counts diverge, I had
confirmation the join was the actual defect, not just an unnecessary
join — it was quietly relying on ORM behavior (Python-side dedup) that
only helps if you fetch every matching row.

## The Root Cause

`search_songs()` performed an `outerjoin` against the `song_tags`
association table that isn't used anywhere in its filter, purely as a
leftover/unnecessary join. Joining a many-to-many table produces one SQL
row per matching tag, so a song with N tags contributes N rows to the raw
result set. With no `LIMIT`, SQLAlchemy's ORM happens to deduplicate
full-entity rows by primary key before returning them, which is why the
reported duplication couldn't be reproduced directly. But that dedup
happens in Python after the database has already applied any `LIMIT`, so
the underlying row fan-out is a real, load-bearing defect that surfaces
the instant pagination is introduced (or if a raw/Core query is ever used
instead of the ORM's `Query` API).

## Fix and Side-Effect Check

Removed the unnecessary `.outerjoin(song_tags, Song.id ==
song_tags.c.song_id)` call from `search_songs()` in
`services/search_service.py`, along with the now-unused `Tag`/`song_tags`
imports. The filter only ever needed `Song.title`/`Song.artist`, and tags
are populated separately via the `Song.tags` relationship inside
`to_dict()`, so nothing else depends on the join.

I re-ran the full `tests/test_search.py` suite (covers 0-tag, 1-tag, and
3-tag songs) to confirm no regression, and re-ran the `.limit(2)`
simulation from the reproduction step without the join to confirm the
correct, non-fanned-out song is returned instead.

## Verification

```
Without outerjoin + limit(2): ['Crown Heights Anthem', 'Zzz Other']
```

`pytest tests/test_search.py` — 5/5 passed. Full `pytest tests/` suite
(13 tests) also passes.

## Commit

`fix: remove unnecessary song_tags join from search query`

---
