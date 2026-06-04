import sqlite3
import os
from contextlib import contextmanager
from gevent.queue import Queue

DB_PATH = '/app/data/kinoswipe.db'


ROOM_CHANNELS = {}

def announce_room_update(room_code, payload):

    if room_code in ROOM_CHANNELS:
        for queue in ROOM_CHANNELS[room_code]:
            queue.put(payload)

@contextmanager
def db_session():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS rooms (pairing_code TEXT PRIMARY KEY, movie_data TEXT, ready INTEGER, current_genre TEXT, solo_mode INTEGER DEFAULT 0, backend TEXT DEFAULT "plex")')
        conn.execute('CREATE TABLE IF NOT EXISTS swipes (room_code TEXT, movie_id TEXT, user_id TEXT, direction TEXT, plex_id TEXT)')
        conn.execute('''CREATE TABLE IF NOT EXISTS matches (
            room_code TEXT, movie_id TEXT, title TEXT, thumb TEXT,
            status TEXT DEFAULT "active", plex_id TEXT,
            UNIQUE(room_code, movie_id, plex_id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS library_cache (
            backend TEXT, genre TEXT, user_id TEXT NOT NULL DEFAULT "", movie_data TEXT, updated_at REAL,
            PRIMARY KEY (backend, genre, user_id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS tmdb_cache (
            backend TEXT NOT NULL,
            movie_id TEXT NOT NULL,
            tmdb_id INTEGER,
            updated_at REAL,
            PRIMARY KEY (backend, movie_id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS genre_cache (
            backend TEXT PRIMARY KEY,
            genre_data TEXT,
            updated_at REAL
        )''')

        cursor = conn.execute("PRAGMA table_info(matches)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'status' not in columns:
            conn.execute('ALTER TABLE matches ADD COLUMN status TEXT DEFAULT "active"')
        if 'plex_id' not in columns:
            conn.execute('ALTER TABLE matches ADD COLUMN plex_id TEXT')

        cursor = conn.execute("PRAGMA table_info(swipes)")
        sw_cols = [col[1] for col in cursor.fetchall()]
        if 'plex_id' not in sw_cols:
            conn.execute('ALTER TABLE swipes ADD COLUMN plex_id TEXT')

        cursor = conn.execute("PRAGMA table_info(rooms)")
        room_cols = [col[1] for col in cursor.fetchall()]
        if 'solo_mode' not in room_cols:
            conn.execute('ALTER TABLE rooms ADD COLUMN solo_mode INTEGER DEFAULT 0')
        if 'last_match_data' not in room_cols:
            conn.execute('ALTER TABLE rooms ADD COLUMN last_match_data TEXT')
        if 'backend' not in room_cols:
            conn.execute('ALTER TABLE rooms ADD COLUMN backend TEXT DEFAULT "plex"')

        cursor = conn.execute("PRAGMA table_info(library_cache)")
        cache_cols = [col[1] for col in cursor.fetchall()]
        if 'user_id' not in cache_cols:
            conn.execute('ALTER TABLE library_cache ADD COLUMN user_id TEXT NOT NULL DEFAULT ""')
            conn.execute('''CREATE TABLE IF NOT EXISTS library_cache_new (
                backend TEXT, genre TEXT, user_id TEXT NOT NULL DEFAULT "", movie_data TEXT, updated_at REAL,
                PRIMARY KEY (backend, genre, user_id)
            )''')
            conn.execute('INSERT INTO library_cache_new SELECT backend, genre, "", movie_data, updated_at FROM library_cache')
            conn.execute('DROP TABLE library_cache')
            conn.execute('ALTER TABLE library_cache_new RENAME TO library_cache')

        conn.execute('DELETE FROM swipes WHERE room_code NOT IN (SELECT pairing_code FROM rooms)')
