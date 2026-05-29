import json
import time
import secrets
import random
import requests
import threading
from flask import Blueprint, render_template, jsonify, request, session, Response, abort, send_from_directory
from plexapi.myplex import MyPlexAccount
from gevent.queue import Queue

from app.database import get_db, db_session, ROOM_CHANNELS, announce_room_update
from app.services import (
    CLIENT_ID, JELLYFIN_URL, PLEX_URL, ADMIN_TOKEN, TMDB_API_KEY,
    plex_ready, jellyfin_ready, fetch_jellyfin_movies, fetch_plex_movies, 
    get_jellyfin_item, get_plex, reset_plex, tmdb_search, _jf_headers
)

main_bp = Blueprint('main', __name__)

CACHE_TTL = 43200        
CACHE_TTL_RECENT = 1800  

def get_item_meta(movie_id, backend_override=None):
    backend = backend_override or current_backend()
    if backend == 'jellyfin':
        item = get_jellyfin_item(movie_id)
        return item.get('Name', ''), item.get('ProductionYear')
    else:
        try:
            plex = get_plex()
            item = plex.fetchItem(int(movie_id))
        except Exception:
            reset_plex()
            item = get_plex().fetchItem(int(movie_id))
        return item.title, item.year

def current_backend():
    header_backend = request.headers.get('X-Backend')
    if header_backend in ('plex', 'jellyfin'):
        session['backend'] = header_backend 
        return header_backend
    code = session.get('active_room')
    if code:
        with get_db() as conn:
            row = conn.execute('SELECT backend FROM rooms WHERE pairing_code = ?', (code,)).fetchone()
            if row:
                return row['backend']
    return session.get('backend', 'plex')

def fetch_movies(genre_name=None):
    backend = current_backend()
    genre_name = genre_name or "All"
    
    with db_session() as conn:
        cache = conn.execute(
            'SELECT movie_data, updated_at FROM library_cache WHERE backend = ? AND genre = ?',
            (backend, genre_name)
        ).fetchone()

    now = time.time()
    ttl = CACHE_TTL_RECENT if genre_name == "Recently Added" else CACHE_TTL

    if not cache:
        movie_list = build_and_cache_library(backend, genre_name)
    else:
        movie_list = json.loads(cache['movie_data'])
        if now - cache['updated_at'] > ttl:
            threading.Thread(target=build_and_cache_library, args=(backend, genre_name), daemon=True).start()

    if genre_name != "Recently Added":
        random.shuffle(movie_list)
    return movie_list

def build_and_cache_library(backend, genre_name):
    try:
        if backend == 'jellyfin':
            movies = fetch_jellyfin_movies(genre_name)
        else:
            movies = fetch_plex_movies(genre_name)
            
        if not movies:
            return []

        with db_session() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO library_cache (backend, genre, movie_data, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (backend, genre_name, json.dumps(movies), time.time()))
        return movies
    except Exception:
        return []

def get_genres():
    if current_backend() == 'jellyfin':
        from app.services import get_jellyfin_genres
        return get_jellyfin_genres()
    from app.services import get_plex_genres
    return get_plex_genres()

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/auth/plex-url')
def get_plex_url():
    REDIRECT_URL = f"{request.scheme}://{request.host}"
    headers = {'X-Plex-Product': 'KinoSwipe', 'X-Plex-Client-Identifier': CLIENT_ID, 'Accept': 'application/json'}
    try:
        res = requests.post('https://plex.tv/api/v2/pins?strong=true', headers=headers).json()
        forward = f"{REDIRECT_URL}?pin_id={res['id']}"
        auth_url = (
            f"https://app.plex.tv/auth/#!?clientID={CLIENT_ID}"
            f"&code={res['code']}"
            f"&context%5Bdevice%5D%5Bproduct%5D=KinoSwipe"
            f"&forwardUrl={requests.utils.quote(forward, safe='')}"
        )
        return jsonify({'auth_url': auth_url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@main_bp.route('/auth/check-returned-pin')
def check_pin():
    pin_id = request.args.get('pin_id') or session.get('pending_pin_id')
    if not pin_id:
        return jsonify({'authToken': None})
    headers = {'X-Plex-Client-Identifier': CLIENT_ID, 'Accept': 'application/json'}
    res = requests.get(f"https://plex.tv/api/v2/pins/{pin_id}", headers=headers).json()
    token = res.get('authToken')
    if token:
        session.pop('pending_pin_id', None)
        session['backend'] = 'plex'
    return jsonify({'authToken': token})

@main_bp.route('/auth/jellyfin-login', methods=['POST'])
def jellyfin_login():
    if not jellyfin_ready:
        return jsonify({'error': 'Jellyfin not configured on this server'}), 503
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    if not username:
        return jsonify({'error': 'Username required'}), 400
    try:
        auth_headers = {
            'X-Emby-Authorization': (
                f'MediaBrowser Client="KinoSwipe", Device="Browser", '
                f'DeviceId="{CLIENT_ID}", Version="1.0.0"'
            ),
            'Content-Type': 'application/json',
        }
        res = requests.post(
            f"{JELLYFIN_URL}/Users/AuthenticateByName",
            headers=auth_headers,
            json={'Username': username, 'Pw': password},
            timeout=10,
        )
        if res.status_code == 401:
            return jsonify({'error': 'Invalid username or password'}), 401
        res.raise_for_status()
        body = res.json()
        user = body.get('User', {})
        session['backend'] = 'jellyfin'
        return jsonify({
            'accessToken': body.get('AccessToken'),
            'userId': user.get('Id'),
            'username': user.get('Name'),
        })
    except requests.HTTPError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@main_bp.route('/auth/available-backends')
def available_backends():
    return jsonify({
        'plex': plex_ready,
        'jellyfin': jellyfin_ready,
    })

@main_bp.route('/watchlist/add', methods=['POST'])
def add_to_watchlist():
    data = request.json
    movie_id = data.get('movie_id')
    backend = current_backend()

    if backend == 'jellyfin':
        user_token = request.headers.get('X-Jellyfin-Token')
        user_id = request.headers.get('X-Jellyfin-User-ID')
        if not user_token or not user_id:
            return jsonify({'error': 'Unauthorized'}), 401
        try:
            r = requests.post(
                f"{JELLYFIN_URL}/Users/{user_id}/FavoriteItems/{movie_id}",
                headers={'X-Emby-Token': user_token},
                timeout=10,
            )
            r.raise_for_status()
            return jsonify({'status': 'success'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        try:
            user_token = request.headers.get('X-Plex-Token')
            if not user_token:
                print("[watchlist] Error: Missing X-Plex-Token header", flush=True)
                return jsonify({'error': 'Unauthorized'}), 401
            
        
            account = MyPlexAccount(token=user_token)
            
        
            try:
                plex = get_plex()
                item = plex.fetchItem(int(movie_id))
            except Exception as inner_e:
                print(f"[watchlist] Initial local lookup failed for ID {movie_id}: {inner_e}. Resetting instance...", flush=True)
                reset_plex()
                item = get_plex().fetchItem(int(movie_id))
                
            
            print(f"[watchlist] Attempting to add item '{item.title}' (ID: {movie_id}) to watchlist...", flush=True)
            account.addToWatchlist(item)
            print("[watchlist] Successfully added item to Plex watchlist!", flush=True)
            return jsonify({'status': 'success'})
        except Exception as e:
            import traceback
            print("[watchlist] FATAL CRASH IN PLEX WATCHLIST LOGIC:", flush=True)
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

@main_bp.route('/server-info')
def get_server_info():
    backend = current_backend()
    try:
        if backend == 'jellyfin':
            r = requests.get(f"{JELLYFIN_URL}/System/Info/Public", headers=_jf_headers(), timeout=10)
            r.raise_for_status()
            info = r.json()
            return jsonify({'name': info.get('ServerName', 'Jellyfin'), 'backend': 'jellyfin'})
        else:
            try:
                plex = get_plex()
            except Exception:
                reset_plex()
                plex = get_plex()
            return jsonify({'machineIdentifier': plex.machineIdentifier, 'name': plex.friendlyName, 'backend': 'plex'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@main_bp.route('/plex/server-info')
def plex_server_info_compat():
    return get_server_info()

@main_bp.route('/get-trailer/<movie_id>')
def get_trailer(movie_id):
    try:
        backend_override = request.headers.get('X-Backend')
        print(f"[trailer] movie_id={movie_id} backend_override={backend_override} session_backend={session.get('backend')} active_room={session.get('active_room')}", flush=True)
        title, year = get_item_meta(movie_id, backend_override)
        print(f"[trailer] title={title!r} year={year!r}", flush=True)
        tmdb_id = tmdb_search(title, year)
        print(f"[trailer] tmdb_id={tmdb_id}", flush=True)
        if tmdb_id:
            v_res = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/videos?api_key={TMDB_API_KEY}").json()
            trailers = [v for v in v_res.get('results', []) if v['site'] == 'YouTube' and v['type'] == 'Trailer']
            if trailers:
                return jsonify({'youtube_key': trailers[0]['key']})
        return jsonify({'error': 'Not found'}), 404
    except Exception as e:
        print(f"[trailer] EXCEPTION: {e}", flush=True)
        return jsonify({'error': str(e)}), 500

@main_bp.route('/cast/<movie_id>')
def get_cast(movie_id):
    try:
        backend_override = request.headers.get('X-Backend')
        title, year = get_item_meta(movie_id, backend_override)
        tmdb_id = tmdb_search(title, year)
        if tmdb_id:
            c_res = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/credits?api_key={TMDB_API_KEY}").json()
            cast = []
            for actor in c_res.get('cast', [])[:8]:
                cast.append({
                    'name': actor['name'],
                    'character': actor.get('character', ''),
                    'profile_path': f"https://image.tmdb.org/t/p/w185{actor['profile_path']}" if actor.get('profile_path') else None
                })
            return jsonify({'cast': cast})
        return jsonify({'cast': []})
    except Exception as e:
        return jsonify({'error': str(e), 'cast': []}), 500

@main_bp.route('/room/create', methods=['POST'])
def create_room():
    backend = session.get('backend', 'plex')
    pairing_code = str(random.randint(1000, 9999))
    movie_list = fetch_movies()
    with get_db() as conn:
        conn.execute(
            'INSERT INTO rooms (pairing_code, movie_data, ready, current_genre, solo_mode, backend) VALUES (?, ?, ?, ?, ?, ?)',
            (pairing_code, json.dumps(movie_list), 0, 'All', 0, backend)
        )
    session['active_room'] = pairing_code
    session['my_user_id'] = 'host_' + secrets.token_hex(8)
    session['solo_mode'] = False
    return jsonify({'pairing_code': pairing_code})

@main_bp.route('/room/go-solo', methods=['POST'])
def go_solo():
    code = session.get('active_room')
    if not code:
        return jsonify({'error': 'No active room'}), 400
    with get_db() as conn:
        conn.execute('UPDATE rooms SET ready = 1, solo_mode = 1 WHERE pairing_code = ?', (code,))
    session['solo_mode'] = True
    
    announce_room_update(code, {'ready': True, 'solo': True})
    return jsonify({'status': 'solo'})

@main_bp.route('/room/join', methods=['POST'])
def join_room():
    code = request.json.get('code')
    joiner_backend = session.get('backend', 'plex')
    with get_db() as conn:
        room = conn.execute('SELECT * FROM rooms WHERE pairing_code = ?', (code,)).fetchone()
        if room:
            if room['backend'] != joiner_backend:
                return jsonify({
                    'error': f"This room uses {room['backend'].capitalize()}. Please log in with {room['backend'].capitalize()} to join."
                }), 409
            conn.execute('UPDATE rooms SET ready = 1 WHERE pairing_code = ?', (code,))
            session['active_room'] = code
            session['my_user_id'] = 'guest_' + secrets.token_hex(8)
            session['solo_mode'] = False
            
            announce_room_update(code, {'ready': True, 'solo': False})
            return jsonify({'status': 'success'})
    return jsonify({'error': 'Invalid Code'}), 404

@main_bp.route('/room/swipe', methods=['POST'])
def swipe():
    code = session.get('active_room')
    uid = session.get('my_user_id')
    data = request.json
    mid, title, thumb = str(data.get('movie_id')), data.get('title'), data.get('thumb')
    plex_id = data.get('plex_id')

    if not code:
        return jsonify({'match': False})

    with get_db() as conn:
        conn.execute('INSERT INTO swipes (room_code, movie_id, user_id, direction, plex_id) VALUES (?, ?, ?, ?, ?)',
                     (code, mid, uid, data.get('direction'), plex_id))

        if data.get('direction') == 'right':
            room = conn.execute('SELECT solo_mode FROM rooms WHERE pairing_code = ?', (code,)).fetchone()
            if room and room['solo_mode']:
                conn.execute(
                    'INSERT OR IGNORE INTO matches (room_code, movie_id, title, thumb, status, plex_id) VALUES (?, ?, ?, ?, "active", ?)',
                    (code, mid, title, thumb, plex_id)
                )
                return jsonify({'match': True, 'title': title, 'thumb': thumb, 'solo': True})

            other_swipe = conn.execute(
                'SELECT plex_id FROM swipes WHERE room_code = ? AND movie_id = ? AND direction = "right" AND user_id != ?',
                (code, mid, uid)
            ).fetchone()

            if other_swipe:
                conn.execute(
                    'INSERT OR IGNORE INTO matches (room_code, movie_id, title, thumb, status, plex_id) VALUES (?, ?, ?, ?, "active", ?)',
                    (code, mid, title, thumb, plex_id)
                )
                if other_swipe['plex_id'] and other_swipe['plex_id'] != plex_id:
                    conn.execute(
                        'INSERT OR IGNORE INTO matches (room_code, movie_id, title, thumb, status, plex_id) VALUES (?, ?, ?, ?, "active", ?)',
                        (code, mid, title, thumb, other_swipe['plex_id'])
                    )
                match_data = {'title': title, 'thumb': thumb, 'ts': time.time()}
                conn.execute('UPDATE rooms SET last_match_data = ? WHERE pairing_code = ?', (json.dumps(match_data), code))
                
                announce_room_update(code, {'last_match': match_data})
                return jsonify({'match': True, 'title': title, 'thumb': thumb})

    return jsonify({'match': False})

@main_bp.route('/room/status')
def room_status():
    code = session.get('active_room')
    if not code:
        return jsonify({'ready': False})
    with get_db() as conn:
        room = conn.execute('SELECT ready, current_genre, solo_mode, last_match_data, backend FROM rooms WHERE pairing_code = ?', (code,)).fetchone()
        if room:
            last_match = json.loads(room['last_match_data']) if room['last_match_data'] else None
            return jsonify({
                'ready': bool(room['ready']),
                'genre': room['current_genre'],
                'solo': bool(room['solo_mode']),
                'last_match': last_match,
                'backend': room['backend'],
            })
        return jsonify({'ready': False})

@main_bp.route('/room/quit', methods=['POST'])
def quit_room():
    code = session.get('active_room')
    if code:
        with get_db() as conn:
            conn.execute('DELETE FROM rooms WHERE pairing_code = ?', (code,))
            conn.execute('DELETE FROM swipes WHERE room_code = ?', (code,))
            conn.execute('UPDATE matches SET status = "archived", room_code = "HISTORY" WHERE room_code = ? AND status = "active"', (code,))
        session.pop('active_room', None)
        session.pop('solo_mode', None)
        
        announce_room_update(code, {'closed': True})
    return jsonify({'status': 'session_ended'})

@main_bp.route('/room/stream')
def room_stream():
    code = session.get('active_room')
    if not code:
        return Response("data: {}\n\n", mimetype='text/event-stream')

    def generate():
        q = Queue()
        if code not in ROOM_CHANNELS:
            ROOM_CHANNELS[code] = []
        ROOM_CHANNELS[code].append(q)

        try:
            while True:
                payload = q.get()
                yield f"data: {json.dumps(payload)}\n\n"
                if payload.get('closed'):
                    break
        except GeneratorExit:
            pass
        finally:
            if code in ROOM_CHANNELS and q in ROOM_CHANNELS[code]:
                ROOM_CHANNELS[code].remove(q)
                if not ROOM_CHANNELS[code]:
                    del ROOM_CHANNELS[code]

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@main_bp.route('/movies')
def get_movies():
    code = session.get('active_room')
    genre = request.args.get('genre')
    if not code:
        return jsonify([])
    with get_db() as conn:
        if genre:
            new_list = fetch_movies(genre)
            conn.execute('UPDATE rooms SET movie_data = ?, current_genre = ? WHERE pairing_code = ?',
                         (json.dumps(new_list), genre, code))
            
            announce_room_update(code, {'genre': genre})
            return jsonify(new_list)
        room = conn.execute('SELECT movie_data FROM rooms WHERE pairing_code = ?', (code,)).fetchone()
        return Response(room['movie_data'], mimetype='application/json') if room else jsonify([])

@main_bp.route('/genres')
def genres_route():
    return jsonify(get_genres())

@main_bp.route('/matches')
def get_matches():
    code = session.get('active_room')
    view = request.args.get('view')
    plex_id = request.headers.get('X-Plex-User-ID') or request.headers.get('X-Jellyfin-User-ID')
    with get_db() as conn:
        if view == 'history':
            rows = conn.execute('SELECT title, thumb, movie_id FROM matches WHERE status = "archived" AND plex_id = ?', (plex_id,)).fetchall()
        else:
            rows = conn.execute('SELECT title, thumb, movie_id FROM matches WHERE room_code = ? AND status = "active" AND plex_id = ?', (code, plex_id)).fetchall()
        return jsonify([dict(row) for row in rows])

@main_bp.route('/matches/delete', methods=['POST'])
def delete_match():
    mid = str(request.json.get('movie_id'))
    plex_id = request.headers.get('X-Plex-User-ID') or request.headers.get('X-Jellyfin-User-ID')
    with get_db() as conn:
        conn.execute('DELETE FROM matches WHERE movie_id = ? AND plex_id = ?', (mid, plex_id))
    return jsonify({'status': 'deleted'})

@main_bp.route('/undo', methods=['POST'])
def undo_swipe():
    code = session.get('active_room')
    uid = session.get('my_user_id')
    mid = str(request.json.get('movie_id'))
    plex_id = request.headers.get('X-Plex-User-ID') or request.headers.get('X-Jellyfin-User-ID')
    with get_db() as conn:
        conn.execute('DELETE FROM swipes WHERE room_code = ? AND movie_id = ? AND user_id = ?', (code, mid, uid))
        conn.execute('DELETE FROM matches WHERE room_code = ? AND movie_id = ? AND status = "active" AND plex_id = ?', (code, mid, plex_id))
    return jsonify({'status': 'undone'})

@main_bp.route('/proxy')
def proxy():
    backend = request.args.get('backend', 'plex')

    if backend == 'jellyfin':
        item_id = request.args.get('item_id')
        if not item_id:
            abort(400)
        img_url = f"{JELLYFIN_URL}/Items/{item_id}/Images/Primary"
        res = requests.get(img_url, headers=_jf_headers(), stream=True, timeout=10)
        return Response(res.content, content_type=res.headers.get('Content-Type', 'image/jpeg'))

    else:  # plex
        path = request.args.get('path')
        if not path or not path.startswith("/library/metadata/"):
            abort(403)
        res = requests.get(f"{PLEX_URL}{path}?X-Plex-Token={ADMIN_TOKEN}", stream=True, timeout=10)
        return Response(res.content, content_type=res.headers['Content-Type'])

@main_bp.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

@main_bp.route('/sw.js')
def serve_sw():
    return send_from_directory('../data', 'sw.js')

@main_bp.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)
