import threading
import time
import traceback

import requests

from app.database import db_session
from app.services import get_plex, get_plex_movie_section, ADMIN_TOKEN

COLLECTION_TITLE = "Kino Swipe Matches"
LABEL_PREFIX = "KSH-hide-"
OWNER_LABEL_PREFIX = "KSH-owner-"
EXPIRY_SECONDS = 365 * 86400 * 100

_account_lock = threading.Lock()

_collection_locks = {}
_collection_locks_guard = threading.Lock()


def _get_collection_lock(plex_id):
    plex_id = str(plex_id)
    with _collection_locks_guard:
        if plex_id not in _collection_locks:
            _collection_locks[plex_id] = threading.Lock()
        return _collection_locks[plex_id]

_admin_account = None
_admin_id = None


def _get_admin_account():
    global _admin_account, _admin_id
    with _account_lock:
        if _admin_account is None:
            from plexapi.myplex import MyPlexAccount
            _admin_account = MyPlexAccount(token=ADMIN_TOKEN)
            _admin_id = str(_admin_account.id)
        return _admin_account


def _get_display_name(plex_id):
    plex_id = str(plex_id)
    account = _get_admin_account()

    if plex_id == _admin_id:
        name = getattr(account, "title", "") or getattr(account, "username", "")
        return name.strip() if name else plex_id

    try:
        for user in account.users():
            if str(user.id) == plex_id:
                name = getattr(user, "title", "") or getattr(user, "username", "")
                return name.strip() if name else plex_id
    except Exception as e:
        print(f"[homescreen] Failed to resolve display name for {plex_id}: {e}", flush=True)

    return plex_id


def _is_admin(plex_id):
    _get_admin_account()
    return str(plex_id) == _admin_id


def _all_other_user_ids(exclude_plex_id):
    account = _get_admin_account()
    exclude_str = str(exclude_plex_id)
    others = []
    try:
        for user in account.users():
            servers = getattr(user, "servers", []) or []
            if not servers or all(getattr(s, "pending", False) for s in servers):
                continue
            uid = str(user.id)
            if uid == exclude_str or uid == _admin_id:
                continue
            others.append(uid)
    except Exception as e:
        print(f"[homescreen] Failed to list Plex users: {e}", flush=True)
    return others


def _is_homescreen_enabled(plex_id):
    with db_session() as conn:
        row = conn.execute(
            'SELECT enabled FROM homescreen_sync WHERE plex_id = ?', (str(plex_id),)
        ).fetchone()
        return row is None or bool(row['enabled'])


def _get_sync_row(plex_id):
    with db_session() as conn:
        return conn.execute(
            'SELECT * FROM homescreen_sync WHERE plex_id = ?', (str(plex_id),)
        ).fetchone()


def _save_sync_row(plex_id, rating_key=None, targeting_applied=None, enabled=None):
    with db_session() as conn:
        existing = conn.execute(
            'SELECT * FROM homescreen_sync WHERE plex_id = ?', (str(plex_id),)
        ).fetchone()
        if existing is None:
            conn.execute(
                'INSERT INTO homescreen_sync (plex_id, enabled, rating_key, targeting_applied) VALUES (?, ?, ?, ?)',
                (str(plex_id), 1 if enabled is None else int(enabled),
                 rating_key, int(bool(targeting_applied)))
            )
        else:
            new_rating_key = rating_key if rating_key is not None else existing['rating_key']
            new_targeting = int(bool(targeting_applied)) if targeting_applied is not None else existing['targeting_applied']
            new_enabled = int(enabled) if enabled is not None else existing['enabled']
            conn.execute(
                'UPDATE homescreen_sync SET rating_key = ?, targeting_applied = ?, enabled = ? WHERE plex_id = ?',
                (new_rating_key, new_targeting, new_enabled, str(plex_id))
            )


def _merge_filter_exclusion(existing_filter, label):
    label_lower = label.lower()
    if not existing_filter:
        return f"label!={label}"

    parts = existing_filter.split("&")
    other_parts = []
    existing_labels = []
    for part in parts:
        if part.startswith("label!="):
            for lbl in part[len("label!="):].split(","):
                lbl = lbl.strip()
                if lbl and lbl.lower() != label_lower:
                    existing_labels.append(lbl)
        else:
            other_parts.append(part)

    existing_labels.append(label)
    return "&".join(other_parts + [f"label!={','.join(existing_labels)}"])


def _apply_filter_exclusion(user_id, label):
    base_url = (
        "https://clients.plex.tv/api/v2/sharing_settings"
        "?X-Plex-Product=Kino+Swipe&X-Plex-Client-Identifier=KinoSwipe-Bergasha-2026"
    )
    headers = {"Accept": "application/json", "X-Plex-Token": ADMIN_TOKEN}

    try:
        resp = requests.get(f"{base_url}&invitedId={user_id}", headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"[homescreen] Could not read filters for user {user_id} (status {resp.status_code})", flush=True)
            return False
        data = resp.json()
        new_movies = _merge_filter_exclusion(data.get("filterMovies", "") or "", label)
        new_tv = _merge_filter_exclusion(data.get("filterTelevision", "") or "", label)

        payload = {
            "settings": {
                "filterMovies": new_movies,
                "filterTelevision": new_tv,
                "filterMusic": data.get("filterMusic", "") or "",
            },
            "invitedId": user_id,
        }
        resp = requests.post(base_url, json=payload, headers=headers, timeout=10)
        return resp.status_code in (200, 201)
    except Exception as e:
        print(f"[homescreen] Failed to apply filter exclusion for user {user_id}: {e}", flush=True)
        return False


def _apply_one_time_targeting(plex_id, collection):
    label = f"{LABEL_PREFIX}{plex_id}"
    others = _all_other_user_ids(exclude_plex_id=plex_id)

    for uid in others:
        try:
            collection.addLabel(label)
        except Exception as e:
            print(f"[homescreen] Failed to add label to collection for {plex_id}: {e}", flush=True)
            traceback.print_exc()
            break

    ok_count = 0
    for uid in others:
        if _apply_filter_exclusion(uid, label):
            ok_count += 1

    print(f"[homescreen] Targeting applied for plex_id={plex_id}: hidden from {ok_count}/{len(others)} other users", flush=True)

    try:
        if _is_admin(plex_id):
            collection.visibility().promoteHome()
        else:
            collection.visibility().promoteShared()
    except Exception as e:
        print(f"[homescreen] Failed to promote collection for {plex_id}: {e}", flush=True)
        traceback.print_exc()

    _save_sync_row(plex_id, targeting_applied=True)


def _get_collection(plex_id):
    plex_id = str(plex_id)
    owner_label = f"{OWNER_LABEL_PREFIX}{plex_id}"
    row = _get_sync_row(plex_id)

    if row and row['rating_key']:
        try:
            plex = get_plex()
            return plex.fetchItem(int(row['rating_key']))
        except Exception as e:
            print(f"[homescreen] Stored rating_key for {plex_id} didn't resolve ({e}), falling back to label search", flush=True)

    try:
        plex = get_plex()
        section = get_plex_movie_section(plex)
        matches = section.search(libtype='collection', label=owner_label)
        if matches:
            found = matches[0]
            _save_sync_row(plex_id, rating_key=found.ratingKey)
            print(f"[homescreen] Recovered existing collection for {plex_id} via label search, DB pointer was stale", flush=True)
            return found
    except Exception as e:
        print(f"[homescreen] Label-based fallback search failed for {plex_id}: {e}", flush=True)

    return None


def _track_added(plex_id, movie_rating_key):
    with db_session() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO homescreen_items (plex_id, movie_id, added_at) VALUES (?, ?, ?)',
            (str(plex_id), str(movie_rating_key), time.time())
        )


def _untrack(plex_id, movie_rating_key):
    with db_session() as conn:
        conn.execute(
            'DELETE FROM homescreen_items WHERE plex_id = ? AND movie_id = ?',
            (str(plex_id), str(movie_rating_key))
        )


def _cleanup_expired_for_user(plex_id):
    plex_id = str(plex_id)
    cutoff = time.time() - EXPIRY_SECONDS
    with db_session() as conn:
        rows = conn.execute(
            'SELECT movie_id FROM homescreen_items WHERE plex_id = ? AND added_at < ?',
            (plex_id, cutoff)
        ).fetchall()
    if not rows:
        return

    with _get_collection_lock(plex_id):
        collection = _get_collection(plex_id)
        expired_count = 0
        for row in rows:
            mid = row['movie_id']
            try:
                if collection:
                    movie = next((i for i in collection.items() if i.ratingKey == int(mid)), None)
                    if movie:
                        collection.removeItems([movie])
                expired_count += 1
            except Exception as e:
                print(f"[homescreen] Failed to expire movie {mid} for {plex_id}: {e}", flush=True)
            _untrack(plex_id, mid)

    if expired_count:
        print(f"[homescreen] Expired {expired_count} item(s) (>7 days) from {plex_id}'s homescreen collection", flush=True)


def cleanup_expired_async(plex_id):
    if not plex_id:
        return
    threading.Thread(target=_cleanup_expired_for_user, args=(str(plex_id),), daemon=True).start()


def _sync_add(plex_id, movie_rating_key):
    if not plex_id or not _is_homescreen_enabled(plex_id):
        return
    try:
        _cleanup_expired_for_user(plex_id)

        plex = get_plex()
        section = get_plex_movie_section(plex)
        movie = plex.fetchItem(int(movie_rating_key))

        with _get_collection_lock(plex_id):
            collection = _get_collection(plex_id)
            newly_created = False

            if collection is None:
                display_name = _get_display_name(plex_id)
                title = f"{display_name}'s {COLLECTION_TITLE}"
                try:
                    collection = section.createCollection(title=title, items=[movie])
                except Exception as e:
                    print(f"[homescreen] Create with title '{title}' failed ({e}), retrying with plex_id suffix", flush=True)
                    title = f"{display_name}'s {COLLECTION_TITLE} ({plex_id})"
                    collection = section.createCollection(title=title, items=[movie])
                
             
                try:
                    collection.modeUpdate(mode='hide')
                    print(f"[homescreen] Successfully set collectionMode to hide for {plex_id}", flush=True)
                except Exception as mode_err:
                    print(f"[homescreen] Failed to update collection mode via library method ({mode_err}), trying explicit edit", flush=True)
                    try:
                        collection.edit(**{"collectionMode": 0})
                    except Exception as edit_err:
                        print(f"[homescreen] Critical: Could not hide collection container from library view: {edit_err}", flush=True)
        

                collection.librarySectionID = int(section.key)
                collection.addLabel(f"{OWNER_LABEL_PREFIX}{plex_id}")
                _save_sync_row(plex_id, rating_key=collection.ratingKey, targeting_applied=False)
                newly_created = True
            else:
                existing_keys = {item.ratingKey for item in collection.items()}
                if movie.ratingKey not in existing_keys:
                    collection.addItems([movie])

            _track_added(plex_id, movie.ratingKey)

            if newly_created:
                _apply_one_time_targeting(plex_id, collection)

    except Exception as e:
        print(f"[homescreen] Failed to sync match add for plex_id={plex_id}, movie={movie_rating_key}: {e}", flush=True)
        traceback.print_exc()


def _sync_remove(plex_id, movie_rating_key):
    if not plex_id:
        return
    try:
        with _get_collection_lock(plex_id):
            collection = _get_collection(plex_id)
            if collection is not None:
                movie = next((i for i in collection.items() if i.ratingKey == int(movie_rating_key)), None)
                if movie:
                    collection.removeItems([movie])
            _untrack(plex_id, movie_rating_key)
    except Exception as e:
        print(f"[homescreen] Failed to sync match removal for plex_id={plex_id}, movie={movie_rating_key}: {e}", flush=True)


def add_match_async(plex_id, movie_rating_key):
    if not plex_id:
        return
    threading.Thread(target=_sync_add, args=(plex_id, movie_rating_key), daemon=True).start()


def remove_match_async(plex_id, movie_rating_key):
    if not plex_id:
        return
    threading.Thread(target=_sync_remove, args=(plex_id, movie_rating_key), daemon=True).start()


def set_homescreen_enabled(plex_id, enabled):
    _save_sync_row(plex_id, enabled=enabled)

    def _toggle_visibility():
        try:
            collection = _get_collection(plex_id)
            if collection is None:
                return
            hub = collection.visibility()
            if _is_admin(plex_id):
                hub.updateVisibility(home=bool(enabled))
            else:
                hub.updateVisibility(shared=bool(enabled))
        except Exception as e:
            print(f"[homescreen] Failed to toggle visibility for plex_id={plex_id}: {e}", flush=True)

    threading.Thread(target=_toggle_visibility, daemon=True).start()


def get_homescreen_enabled(plex_id):
    return _is_homescreen_enabled(plex_id)


_onboarding_lock = threading.Lock()
_onboarding_in_progress = set()


def _get_existing_collection_owners(exclude_plex_id):
    exclude_str = str(exclude_plex_id)
    with db_session() as conn:
        rows = conn.execute(
            'SELECT plex_id FROM homescreen_sync WHERE targeting_applied = 1'
        ).fetchall()
    return [r['plex_id'] for r in rows if r['plex_id'] != exclude_str]


def _onboard_new_user(plex_id):
    plex_id = str(plex_id)
    try:
        if _is_admin(plex_id):
            _save_sync_row(plex_id, enabled=True)
            return

        owners = _get_existing_collection_owners(exclude_plex_id=plex_id)
        applied = 0
        for owner_id in owners:
            label = f"{LABEL_PREFIX}{owner_id}"
            if _apply_filter_exclusion(plex_id, label):
                applied += 1
        print(
            f"[homescreen] Onboarded new user {plex_id}: "
            f"retroactively hid {applied}/{len(owners)} existing collections", flush=True
        )
        _save_sync_row(plex_id, enabled=True)
    finally:
        with _onboarding_lock:
            _onboarding_in_progress.discard(plex_id)


def ensure_user_known(plex_id):
    if not plex_id:
        return
    plex_id = str(plex_id)
    if _get_sync_row(plex_id) is not None:
        return

    with _onboarding_lock:
        if plex_id in _onboarding_in_progress:
            return
        _onboarding_in_progress.add(plex_id)

    threading.Thread(target=_onboard_new_user, args=(plex_id,), daemon=True).start()
