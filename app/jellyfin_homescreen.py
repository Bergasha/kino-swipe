import threading
import time

import requests

from app.database import db_session
from app.services import JELLYFIN_URL, _jf_headers


def _is_homescreen_enabled(user_id):
    with db_session() as conn:
        row = conn.execute(
            'SELECT enabled FROM homescreen_sync WHERE plex_id = ?', (str(user_id),)
        ).fetchone()
        return row is None or bool(row['enabled'])


def _save_enabled(user_id, enabled):
    with db_session() as conn:
        existing = conn.execute(
            'SELECT * FROM homescreen_sync WHERE plex_id = ?', (str(user_id),)
        ).fetchone()
        if existing is None:
            conn.execute(
                'INSERT INTO homescreen_sync (plex_id, enabled) VALUES (?, ?)',
                (str(user_id), int(enabled))
            )
        else:
            conn.execute(
                'UPDATE homescreen_sync SET enabled = ? WHERE plex_id = ?',
                (int(enabled), str(user_id))
            )


def _tracked_items(user_id):
    with db_session() as conn:
        return conn.execute(
            'SELECT movie_id FROM homescreen_items WHERE plex_id = ?', (str(user_id),)
        ).fetchall()


def _track_added(user_id, movie_id):
    with db_session() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO homescreen_items (plex_id, movie_id, added_at) VALUES (?, ?, ?)',
            (str(user_id), str(movie_id), time.time())
        )


def _untrack(user_id, movie_id):
    with db_session() as conn:
        conn.execute(
            'DELETE FROM homescreen_items WHERE plex_id = ? AND movie_id = ?',
            (str(user_id), str(movie_id))
        )


def _set_favorite(user_id, movie_id, favorite):
    method = requests.post if favorite else requests.delete
    try:
        r = method(
            f"{JELLYFIN_URL}/Users/{user_id}/FavoriteItems/{movie_id}",
            headers=_jf_headers(), timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        action = 'favorite' if favorite else 'unfavorite'
        print(f"[jellyfin-homescreen] Failed to {action} {movie_id} for user {user_id}: {e}", flush=True)
        return False


def _sync_add(user_id, movie_id):
    if not _is_homescreen_enabled(user_id):
        return
    if _set_favorite(user_id, movie_id, favorite=True):
        _track_added(user_id, movie_id)


def _sync_remove(user_id, movie_id):
    _set_favorite(user_id, movie_id, favorite=False)
    _untrack(user_id, movie_id)


def add_match_async(user_id, movie_id):
    if not user_id:
        return
    threading.Thread(target=_sync_add, args=(user_id, movie_id), daemon=True).start()


def remove_match_async(user_id, movie_id):
    if not user_id:
        return
    threading.Thread(target=_sync_remove, args=(user_id, movie_id), daemon=True).start()


def get_homescreen_enabled(user_id):
    return _is_homescreen_enabled(user_id)


def _apply_toggle(user_id, enabled):
    # Jellyfin has no per-collection "hide from home" switch like Plex hubs do,
    # so turning sync off/on means literally un/re-favoriting everything tracked.
    for row in _tracked_items(user_id):
        _set_favorite(user_id, row['movie_id'], favorite=enabled)


def set_homescreen_enabled(user_id, enabled):
    _save_enabled(user_id, enabled)
    threading.Thread(target=_apply_toggle, args=(user_id, enabled), daemon=True).start()
