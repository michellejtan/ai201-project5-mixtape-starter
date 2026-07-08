# Project 5: Mixtape Bug Hunt Submission
# AI Assistance

I used ChatGPT for two specific purposes on this project. First, I asked it to help me understand the overall Flask/SQLAlchemy architecture (e.g. how the app factory and blueprint registration in `app.py` fit together, and what `outerjoin` does against an association table) so I could read unfamiliar code faster before tracing bugs myself. Second, for Bug Fixes 1, 4, and 5, I asked ChatGPT to draft `flask shell` scripts I could use to reproduce each bug (creating users/songs, calling the buggy function, printing the result).

The scripts ChatGPT produced were not directly runnable against this project's actual data — it used placeholder/generic values (e.g. `song1 = Song.query.get(1)`, `create_playlist("Bug Test Playlist", "1")`), since it had no visibility into the real seeded database. Before running them, I had to query the actual `User`/`Song`/`Playlist` records myself (as shown in the `flask shell` output under Bug Fix 1 and Bug Fix 4) and substitute the real UUIDs and IDs from this project in place of ChatGPT's generic placeholders. The reproduction steps recorded under each bug fix reflect that corrected, project-specific version of the script, not what ChatGPT originally generated. I reproduced each bug myself, traced the relevant execution flow through the route and service layers, and implemented and verified the fixes locally — AI was used for scaffolding and architectural understanding, not for generating the fixes themselves.

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

# Bug Fix 4

## Issue

Issue #4: "I got notified when a friend added my song to a playlist but not
when they rated it." Rating a song silently updates the `Rating` row but
never notifies the song's original sharer, unlike `add_to_playlist()`,
which does notify.

## How I Reproduced It

In `services/notification_service.py`, `rate_song()` looks up the song and
rater, creates/updates the `Rating` row, commits, and returns — it never
calls `create_notification()`. Compare to `add_to_playlist()` just above
it, which explicitly calls `create_notification()` after adding the song.

To trigger it, I created a `sharer` user who shares a song and a separate
`rater` user, called `rate_song(rater.id, song.id, 5)`, then called
`get_notifications(sharer.id)`. Expected: one `song_rated` notification for
the sharer. Actual: empty list — no notification was created at all.

```
Notifications for sharer after rating: []
BUG REPRODUCED: sharer got no notification for the rating
```
>>> from models import User, Song
>>> from services.notification_service import rate_song, get_notifications
>>> from app import db
>>> 
>>> for user in User.query.all():
...      print(user.id, user.username)
... 
56db9ce4-ee3b-4f97-8418-88459b35cefc nova
a4c20af5-0419-4345-92a3-3d5244dfa61d darius
6ba98f19-e1ea-43b9-b979-0dcf7035dac1 simone
29a03c95-011a-4a0d-af53-c08cec401888 kenji
ea5dab2d-1004-4637-ae3f-3216d7a63d9e aaliya
>>> for song in Song.query.all():
...      print(song.id, song.title, song.shared_by)
... 
3f5b724f-cab9-4084-b66c-866c231ebfb3 Midnight Drive 56db9ce4-ee3b-4f97-8418-88459b35cefc
926f6c09-0a95-40c8-914e-b7993cc0b577 Still Waters 56db9ce4-ee3b-4f97-8418-88459b35cefc
b122e256-8649-48ca-9968-7d7aa8d7e404 First Light 56db9ce4-ee3b-4f97-8418-88459b35cefc
3cf3958c-39bc-4d2f-b86e-06546053017e Block Party a4c20af5-0419-4345-92a3-3d5244dfa61d
e9ad6c56-19cf-478e-9a8d-f0d099fc25e4 Late Night Session a4c20af5-0419-4345-92a3-3d5244dfa61d
14ff34ce-7f32-4432-b1c8-aa90aeedd3b1 Golden Hour a4c20af5-0419-4345-92a3-3d5244dfa61d
1dd4a1df-abc0-4802-9138-e78c30c5da42 Free Throws a4c20af5-0419-4345-92a3-3d5244dfa61d
147ae1c3-0b6d-4340-a525-b0a38180df0d Soft Landing a4c20af5-0419-4345-92a3-3d5244dfa61d
0f5ec406-b0d1-476b-a8d8-a7240c392148 Crown Heights Anthem 6ba98f19-e1ea-43b9-b979-0dcf7035dac1
3b1a2e38-97ac-4b02-b685-02bcaa2b400c Harlem Renaissance 6ba98f19-e1ea-43b9-b979-0dcf7035dac1
9747c5a9-769f-4999-9328-244d0648b0e5 After Hours 6ba98f19-e1ea-43b9-b979-0dcf7035dac1
15c3c667-b27f-4dd7-a976-6665210de37d Lagos to London 6ba98f19-e1ea-43b9-b979-0dcf7035dac1
8a30bcbb-fa96-43df-8902-75dc617deeb7 Frequencies 6ba98f19-e1ea-43b9-b979-0dcf7035dac1
>>> rate_song("29a03c95-011a-4a0d-af53-c08cec401888", "147ae1c3-0b6d-4340-a525-b0a38180df0d",3.5)
<Rating 44bad888-fbdf-491c-ad90-5dbdf2677f86>
>>> get_notifications("a4c20af5-0419-4345-92a3-3d5244dfa61d")
>>> []

## How I Found the Root Cause

Files examined: `routes/songs.py` (to see the `/songs/<id>/rate` route
calls `rate_song()`), then `services/notification_service.py`. Reading
`rate_song()` top-to-bottom: it looks up the song and rater, creates or
updates the `Rating` row, calls `db.session.commit()`, and returns — that
`return rating` is the last line in the function. Scrolling up to the
sibling function `add_to_playlist()`, defined just above it in the same
file, showed the pattern this function was missing: after its own
`db.session.commit()`, it explicitly calls `create_notification(user_id=
song.shared_by, ...)`. `rate_song()` has no equivalent call anywhere in
its body — that absence, not a wrong condition, is the bug.

## Root Cause

`rate_song()` in `services/notification_service.py` persists the `Rating`
row and commits, but never calls `create_notification()` for the song's
sharer — unlike `add_to_playlist()` in the same file, which notifies the
sharer immediately after adding a song. There's no conditional logic
error here; the notification call is simply absent from this function
entirely, so rating a song never produces a `song_rated` notification for
anyone, regardless of who rates it.

## Fix

Added a `create_notification()` call at the end of `rate_song()` in
`services/notification_service.py`, mirroring `add_to_playlist()`'s
pattern: it notifies `song.shared_by` with a `song_rated` notification
containing the rater's username, the song title, and the score, and skips
notifying when `song.shared_by == user_id` (rating your own song).

## Verification

```
Sharer notified after rating by someone else: 1 song_rated
Notifications after self-rating (should still be 1): 1
```

Confirmed the sharer gets exactly one notification after a friend rates
their song, and that self-rating does not add a spurious notification
(matching `add_to_playlist()`'s existing self-add exemption). Checked
`add_to_playlist()` itself and `get_notifications()`/`mark_as_read()` —
none of them read or depend on `rate_song()`'s return value or side
effects, so this addition doesn't affect other notification flows. Full
`pytest tests/` suite (13 tests) still passes.

## Commit

`fix: notify song sharer when their song is rated`

---

# Bug Fix 5

## Issue

Issue #5: "The last song in a playlist never shows up." Viewing a
playlist's songs is always missing the last track by position, regardless
of playlist length.

## How I Reproduced It

In `services/playlist_service.py`, `get_playlist_songs()` orders playlist
entries by position ascending, then does `songs[:-1]` before converting to
dicts — unconditionally dropping the last element of the ordered list, even
though the function's own docstring says it "returns all songs in the
playlist."

To trigger it, I created a playlist with 4 songs (`Song A`–`Song D`) added
at positions 1–4, then called `get_playlist_songs(playlist.id)`. Expected:
all 4 songs, ending with `Song D`. Actual: only 3 songs returned, `Song D`
missing.

```
Playlist has 4 songs: ['Song A', 'Song B', 'Song C', 'Song D']
get_playlist_songs returned 3: ['Song A', 'Song B', 'Song C']
BUG REPRODUCED: last song ('Song D') missing from result
```
>>> from models import User, Song
>>> from models import Playlist
>>> from services.playlist_service import create_playlist, get_playlist_songs
>>> from app import db
>>> from models import Playlist, playlist_entries
>>> playlist_id = "c24189b2-0a57-4553-9e5b-ac23a5054562"
>>> playlist = db.session.get(Playlist, playlist_id)
>>> for song in playlist.songs:
...     print("-", song.title)
... 
>>> playlist.songs
[]
>>> # Add four songs with positions 1-4
>>> db.session.execute(
...     playlist_entries.insert(),
...     [
...         {
...             "playlist_id": playlist_id,
...             "song_id": "3f5b724f-cab9-4084-b66c-866c231ebfb3",
...             "position": 1,
...             "added_by": "56db9ce4-ee3b-4f97-8418-88459b35cefc",
...         },
...         {
...             "playlist_id": playlist_id,
...             "song_id": "926f6c09-0a95-40c8-914e-b7993cc0b577",
...             "position": 2,
...             "added_by": "56db9ce4-ee3b-4f97-8418-88459b35cefc",
...         },
...         {
...             "playlist_id": playlist_id,
...             "song_id": "b122e256-8649-48ca-9968-7d7aa8d7e404",
...             "position": 3,
...             "added_by": "56db9ce4-ee3b-4f97-8418-88459b35cefc",
...         },
...         {
...             "playlist_id": playlist_id,
...             "song_id": "3cf3958c-39bc-4d2f-b86e-06546053017e",
...             "position": 4,
...             "added_by": "56db9ce4-ee3b-4f97-8418-88459b35cefc",
...         },
...     ],
... )
<sqlalchemy.engine.cursor.CursorResult object at 0x7d8fe0302270>
>>> 
>>> db.session.commit()
>>> # Verify the playlist actually has four songs
>>> for song in playlist.songs:
...     print("-", song.title)
... 
- Block Party
- Midnight Drive
- Still Waters
- First Light
>>> print("Relationship count:", len(playlist.songs))
Relationship count: 4
>>> songs = get_playlist_songs(playlist_id)
>>> print("\nSongs returned by get_playlist_songs():")
>>> # Call the function under test

Songs returned by get_playlist_songs():
>>> for song in songs:
...     print("-", song["title"])
... 
- Midnight Drive
- Still Waters
- First Light
>>> print("Returned count:", len(songs))
Returned count: 3
>>> 

## How I Found the Root Cause

Files examined: `routes/playlists.py` (to confirm the songs endpoint calls
`get_playlist_songs()`), then `services/playlist_service.py`. The function
builds an ORM query ordered by `asc(playlist_entries.c.position)` and
assigns it to `songs` — that part matched the docstring exactly. The final
line was `return [song.to_dict() for song in songs[:-1]]`. `songs[:-1]`
is a Python slice that always drops the last element of whatever list
precedes it, unconditionally — that slice, not the query or the ordering,
was the exact cause, since the docstring for the same function explicitly
states "this function returns all songs in the playlist."

## Root Cause

`get_playlist_songs()` in `services/playlist_service.py` correctly
queries and orders all playlist entries by position, but its return
statement applied `songs[:-1]` to the ordered list before converting to
dicts. `[:-1]` always excludes the last element of a list regardless of
its length, so the highest-position song in every playlist — the one most
recently added — was silently dropped from every call, even though
nothing in the query itself limited or excluded it.

## Fix

Changed `return [song.to_dict() for song in songs[:-1]]` to `return
[song.to_dict() for song in songs]` in `services/playlist_service.py`,
so the full ordered list is returned as the docstring describes.

## Verification

```
1-song playlist -> ['Song 0'] (expect 1 song, not 0)
4-song playlist -> ['Song 0', 'Song 1', 'Song 2', 'Song 3'] (expect all 4, ending Song 3)
```

Checked the single-song boundary specifically, since `songs[:-1]` on a
1-element list previously returned an empty list (the most extreme case
of the bug) — it now correctly returns that one song. Also re-checked the
4-song case ends with the last-added song instead of stopping short.
Checked `get_playlist()` and `get_user_playlists()` in the same file —
neither touches `songs[:-1]` or depends on `get_playlist_songs()`'s
return value, so they're unaffected. Full `pytest tests/` suite (13
tests) still passes.

## Commit

`fix: return full song list instead of dropping last playlist entry`

---

# Regression Tests (Stretch)

Four issues now have regression tests in `tests/`, covering all bugs fixed in
this project. Two already existed in the starter repo; two (`test_feed.py`,
`test_notifications.py`) I added for this stretch goal.

## Already present (Issues #1 and #5)

- **`tests/test_streaks.py::test_streak_increments_on_sunday`** — creates a
  user, calls `update_listening_streak()` on a Saturday then a Sunday one
  calendar day apart, and asserts the streak goes from 1 to 2. Against the
  pre-fix code (`elif days_since_last == 1 and today.weekday() != 6:`), the
  `weekday() != 6` clause is `False` on a Sunday regardless of
  `days_since_last`, so the `elif` doesn't match, the `else` branch runs, and
  the streak resets to 1 — this test would have failed with `assert 1 == 2`.
- **`tests/test_playlists.py::test_playlist_returns_all_songs`** — seeds a
  playlist with 5 songs at positions 1–5 and asserts `get_playlist_songs()`
  returns all 5 (comment in the test literally notes "Bug causes this to
  return 4"). Against the pre-fix code (`return [song.to_dict() for song in
  songs[:-1]]`), the last-positioned song is always sliced off, so this test
  would have failed with `assert 4 == 5`.

## Added for this stretch goal (Issues #2 and #4)

- **`tests/test_feed.py::test_friend_listening_2_hours_ago_is_not_shown`** —
  logs a `ListeningEvent` for a friend timestamped 2 hours in the past and
  asserts `get_friends_listening_now()` returns `[]`. I verified this against
  the pre-fix code by temporarily restoring `RECENT_THRESHOLD =
  timedelta(hours=24)`: the 2-hour-old event still satisfies `listened_at >=
  cutoff` under a 24-hour window, so the friend is wrongly included and the
  test fails with `assert [...] == []`. A companion test,
  `test_friend_listening_5_minutes_ago_is_shown`, pins down the other side of
  the boundary so the window can't just be shrunk to zero.
- **`tests/test_notifications.py::test_rating_a_song_notifies_the_sharer`** —
  has one user rate another's shared song via `rate_song()`, then asserts
  `get_notifications()` for the sharer returns exactly one `song_rated`
  notification. I verified this against the pre-fix code by temporarily
  removing the `create_notification()` call from the end of `rate_song()`:
  with no notification ever created, `get_notifications()` returns `[]` and
  the test fails with `assert 0 == 1`. Two companion tests
  (`test_rating_your_own_song_does_not_notify_you` and
  `test_adding_to_playlist_still_notifies_the_sharer`) confirm the self-rating
  exemption and the pre-existing playlist notification path both still work
  after the fix.

I confirmed all four regression tests fail against their respective pre-fix
implementations and pass against the fixed code, then ran the full
`pytest tests/` suite (19 tests) to confirm no regressions elsewhere.

---