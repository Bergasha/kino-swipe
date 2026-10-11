import os
import secrets
import threading

from app.database import db_session

_cache = {}
_lock = threading.Lock()
_listeners = []


def on_change(fn):
    _listeners.append(fn)


def env_value(key):
    value = os.environ.get(key)
    if value and value.strip():
        return value.strip()
    return None


def is_env(key):
    return env_value(key) is not None


def _stored(key):
    with _lock:
        if key in _cache:
            return _cache[key]
    with db_session() as conn:
        row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    value = row['value'] if row else None
    with _lock:
        _cache[key] = value
    return value


def get(key, default=None):
    value = env_value(key)
    if value is None:
        value = _stored(key)
    return value if value else default


def put_many(values):
    with db_session() as conn:
        for key, value in values.items():
            if value is None or value == '':
                conn.execute('DELETE FROM settings WHERE key = ?', (key,))
            else:
                conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
    with _lock:
        _cache.clear()
    changed = set(values)
    for fn in list(_listeners):
        try:
            fn(changed)
        except Exception as e:
            print(f"[config] change listener failed: {e}", flush=True)


def put(key, value):
    put_many({key: value})


def delete(*keys):
    put_many({key: None for key in keys})


def flask_secret():
    value = get('FLASK_SECRET')
    if value:
        return value
    value = secrets.token_hex(32)
    put('FLASK_SECRET', value)
    return value


