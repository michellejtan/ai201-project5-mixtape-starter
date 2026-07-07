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
