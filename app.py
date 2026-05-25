from flask import Flask, send_from_directory, jsonify, request, session, Response, render_template, abort
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount
from werkzeug.middleware.proxy_fix import ProxyFix
from contextlib import contextmanager
import sqlite3, os, random, requests, json, secrets, time, threading

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
app.secret_key = os.environ["FLASK_SECRET"]

DB_PATH = '/app/data/kinoswipe.db'
PLEX_URL = os.getenv('PLEX_URL', '').rstrip('/')
ADMIN_TOKEN = os.getenv('PLEX_TOKEN')
TMDB_API_KEY = os.getenv('TMDB_API_KEY')
CLIENT_ID = 'KinoSwipe-Bergasha-2026'

JELLYFIN_URL = os.getenv('JELLYFIN_URL', '').rstrip('/')
JELLYFIN_API_KEY = os.getenv('JELLYFIN_API_KEY', '')

CACHE_TTL = 86400

if not os.getenv('FLASK_SECRET'):
    raise RuntimeError("Missing env var: FLASK_SECRET")
if not os.getenv('TMDB_API_KEY'):
    raise RuntimeError("Missing env var: TMDB_API_KEY")

plex_ready = bool(PLEX_URL and ADMIN_TOKEN)
jellyfin_ready = bool(JELLYFIN_URL and JELLYFIN_API_KEY)
if not plex_ready and not jellyfin_ready:
    raise RuntimeError("Must set either (PLEX_URL + PLEX_TOKEN) or (JELLYFIN_URL + JELLYFIN_API_KEY)")


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
            backend TEXT, genre TEXT, movie_data TEXT, updated_at REAL,
            PRIMARY KEY (backend, genre)
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

        conn.execute('DELETE FROM swipes WHERE room_code NOT IN (SELECT pairing_code FROM rooms)')



_plex_genre_cache = None
_plex_instance = None

def get_plex():
    global _plex_instance
    if _plex_instance is not None:
        return _plex_instance
    _plex_instance = PlexServer(PLEX_URL, ADMIN_TOKEN)
    return _plex_instance

def reset_plex():
    global _plex_instance
    _plex_instance = None

def get_plex_genres():
    global _plex_genre_cache
    if _plex_genre_cache is not None:
        return _plex_genre_cache
    try:
        plex = get_plex()
        section = plex.library.section('Movies')
        genres = sorted({g.title for g in section.listFilterChoices(field='genre')})
        display = ["Sci-Fi" if g == "Science Fiction" else g for g in genres]
        _plex_genre_cache = display
        return display
    except Exception:
        return []

def fetch_plex_movies(genre_name=None):
    try:
        plex = get_plex()
        movie_section = plex.library.section('Movies')
    except Exception:
        reset_plex()
        plex = get_plex()
        movie_section = plex.library.section('Movies')
    search_genre = "Science Fiction" if genre_name == "Sci-Fi" else genre_name

    if genre_name == "Recently Added":
        movies = movie_section.search(libtype='movie', sort='addedAt:desc', maxresults=100)
    elif search_genre and search_genre != "All":
        movies = movie_section.search(libtype='movie', genre=search_genre, maxresults=2000)
        if not movies and search_genre != genre_name:
            movies = movie_section.search(libtype='movie', genre=genre_name, maxresults=2000)
    else:
        movies = movie_section.search(libtype='movie', maxresults=2000)

    movie_list = []
    for m in movies:
        runtime_str = ""
        if m.duration:
            hrs = m.duration // 3600000
            mins = (m.duration % 3600000) // 60000
            runtime_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"
        movie_list.append({
            'id': str(m.ratingKey), 'title': m.title, 'summary': m.summary,
            'thumb': f"/proxy?backend=plex&path={m.thumb}",
            'rating': m.audienceRating or m.rating, 'duration': runtime_str, 'year': m.year
        })
    return movie_list



_jellyfin_genre_cache = None

def _jf_headers():
    return {
        'X-Emby-Token': JELLYFIN_API_KEY,
        'Content-Type': 'application/json',
    }

def _jf_movie_library_id():
    r = requests.get(f"{JELLYFIN_URL}/Library/VirtualFolders", headers=_jf_headers(), timeout=10)
    r.raise_for_status()
    for folder in r.json():
        if folder.get('CollectionType') == 'movies':
            return folder['ItemId']
    return None

def get_jellyfin_genres():
    global _jellyfin_genre_cache
    if _jellyfin_genre_cache is not None:
        return _jellyfin_genre_cache
    try:
        params = {
            'IncludeItemTypes': 'Movie',
            'EnableImages': 'false',
            'EnableUserData': 'false',
        }
        r = requests.get(f"{JELLYFIN_URL}/Genres", headers=_jf_headers(), params=params, timeout=10)
        r.raise_for_status()
        genres = sorted(g['Name'] for g in r.json().get('Items', []))
        _jellyfin_genre_cache = genres
        return genres
    except Exception:
        return []

def fetch_jellyfin_movies(genre_name=None):
    params = {
        'IncludeItemTypes': 'Movie',
        'Recursive': 'true',
        'Fields': 'Overview,Genres,RunTimeTicks,CommunityRating,ProductionYear',
        'EnableImages': 'true',
        'Limit': 2000,
    }

    if genre_name == "Recently Added":
        params['SortBy'] = 'DateCreated'
        params['SortOrder'] = 'Descending'
        params['Limit'] = 100
    elif genre_name and genre_name != "All":
        params['Genres'] = genre_name

    r = requests.get(f"{JELLYFIN_URL}/Items", headers=_jf_headers(), params=params, timeout=15)
    r.raise_for_status()
    items = r.json().get('Items', [])

    movie_list = []
    for m in items:
        ticks = m.get('RunTimeTicks') or 0
        seconds = ticks // 10_000_000
        hrs, mins = divmod(seconds // 60, 60)
        runtime_str = f"{hrs}h {mins}m" if hrs > 0 else (f"{mins}m" if mins else "")
        movie_list.append({
            'id': m['Id'],
            'title': m.get('Name', ''),
            'summary': m.get('Overview', ''),
            'thumb': f"/proxy?backend=jellyfin&item_id={m['Id']}",
            'rating': round(m.get('CommunityRating'), 1) if m.get('CommunityRating') is not None else None,
            'duration': runtime_str,
            'year': m.get('ProductionYear'),
        })
    return movie_list

def get_jellyfin_item(item_id):
    r = requests.get(
        f"{JELLYFIN_URL}/Items",
        headers=_jf_headers(),
        params={
            'Ids': item_id,
            'Fields': 'Overview,Genres,RunTimeTicks,CommunityRating,ProductionYear',
            'Recursive': 'true',
        },
        timeout=10,
    )
    r.raise_for_status()
    items = r.json().get('Items', [])
    if not items:
        raise ValueError(f"Item {item_id} not found in Jellyfin")
    return items[0]



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

    if not cache:
        movie_list = build_and_cache_library(backend, genre_name)
    else:
        movie_list = json.loads(cache['movie_data'])
        if now - cache['updated_at'] > CACHE_TTL:
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
        return get_jellyfin_genres()
    return get_plex_genres()

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



@app.route('/')
def index():
    return render_template('index.html')



@app.route('/auth/plex-url')
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

@app.route('/auth/check-returned-pin')
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

@app.route('/auth/jellyfin-login', methods=['POST'])
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

@app.route('/auth/available-backends')
def available_backends():
    return jsonify({
        'plex': plex_ready,
        'jellyfin': jellyfin_ready,
    })



@app.route('/watchlist/add', methods=['POST'])
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
                return jsonify({'error': 'Unauthorized'}), 401
            account = MyPlexAccount(token=user_token)
            try:
                plex = get_plex()
                item = plex.fetchItem(int(movie_id))
            except Exception:
                reset_plex()
                item = get_plex().fetchItem(int(movie_id))
            account.addToWatchlist(item)
            return jsonify({'status': 'success'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500



@app.route('/server-info')
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

@app.route('/plex/server-info')
def plex_server_info_compat():
    return get_server_info()



def tmdb_search(title, year):
    base = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={requests.utils.quote(title)}"
    if year:
        r = requests.get(f"{base}&year={year}").json()
        if r.get('results'):
            return r['results'][0]['id']
    r = requests.get(base).json()
    if r.get('results'):
        return r['results'][0]['id']
    return None

@app.route('/get-trailer/<movie_id>')
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

@app.route('/cast/<movie_id>')
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



@app.route('/room/create', methods=['POST'])
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

@app.route('/room/go-solo', methods=['POST'])
def go_solo():
    code = session.get('active_room')
    if not code:
        return jsonify({'error': 'No active room'}), 400
    with get_db() as conn:
        conn.execute('UPDATE rooms SET ready = 1, solo_mode = 1 WHERE pairing_code = ?', (code,))
    session['solo_mode'] = True
    return jsonify({'status': 'solo'})

@app.route('/room/join', methods=['POST'])
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
            return jsonify({'status': 'success'})
    return jsonify({'error': 'Invalid Code'}), 404

@app.route('/room/swipe', methods=['POST'])
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
                match_data = json.dumps({'title': title, 'thumb': thumb, 'ts': time.time()})
                conn.execute('UPDATE rooms SET last_match_data = ? WHERE pairing_code = ?', (match_data, code))
                return jsonify({'match': True, 'title': title, 'thumb': thumb})

    return jsonify({'match': False})

@app.route('/room/status')
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

@app.route('/room/quit', methods=['POST'])
def quit_room():
    code = session.get('active_room')
    if code:
        with get_db() as conn:
            conn.execute('DELETE FROM rooms WHERE pairing_code = ?', (code,))
            conn.execute('DELETE FROM swipes WHERE room_code = ?', (code,))
            conn.execute('UPDATE matches SET status = "archived", room_code = "HISTORY" WHERE room_code = ? AND status = "active"', (code,))
        session.pop('active_room', None)
        session.pop('solo_mode', None)
    return jsonify({'status': 'session_ended'})

@app.route('/room/stream')
def room_stream():
    code = session.get('active_room')
    if not code:
        return Response("data: {}\n\n", mimetype='text/event-stream')

    def generate():
        last_genre = None
        last_ready = None
        last_match_ts = None
        POLL = 1.5
        TIMEOUT = 3600
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            try:
                with get_db() as conn:
                    row = conn.execute(
                        'SELECT ready, current_genre, solo_mode, last_match_data FROM rooms WHERE pairing_code = ?',
                        (code,)
                    ).fetchone()
                if row is None:
                    yield f"data: {json.dumps({'closed': True})}\n\n"
                    return
                ready = bool(row['ready'])
                genre = row['current_genre']
                solo = bool(row['solo_mode'])
                last_match = json.loads(row['last_match_data']) if row['last_match_data'] else None
                match_ts = last_match['ts'] if last_match else None
                payload = {}
                if ready != last_ready:
                    payload['ready'] = ready
                    payload['solo'] = solo
                    last_ready = ready
                if genre != last_genre:
                    payload['genre'] = genre
                    last_genre = genre
                if match_ts and match_ts != last_match_ts:
                    payload['last_match'] = last_match
                    last_match_ts = match_ts
                if payload:
                    yield f"data: {json.dumps(payload)}\n\n"
                time.sleep(POLL)
            except GeneratorExit:
                return
            except Exception:
                time.sleep(POLL)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})



@app.route('/movies')
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
            return jsonify(new_list)
        room = conn.execute('SELECT movie_data FROM rooms WHERE pairing_code = ?', (code,)).fetchone()
        return Response(room['movie_data'], mimetype='application/json') if room else jsonify([])

@app.route('/genres')
def genres_route():
    return jsonify(get_genres())



@app.route('/matches')
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

@app.route('/matches/delete', methods=['POST'])
def delete_match():
    mid = str(request.json.get('movie_id'))
    plex_id = request.headers.get('X-Plex-User-ID') or request.headers.get('X-Jellyfin-User-ID')
    with get_db() as conn:
        conn.execute('DELETE FROM matches WHERE movie_id = ? AND plex_id = ?', (mid, plex_id))
    return jsonify({'status': 'deleted'})

@app.route('/undo', methods=['POST'])
def undo_swipe():
    code = session.get('active_room')
    uid = session.get('my_user_id')
    mid = str(request.json.get('movie_id'))
    plex_id = request.headers.get('X-Plex-User-ID') or request.headers.get('X-Jellyfin-User-ID')
    with get_db() as conn:
        conn.execute('DELETE FROM swipes WHERE room_code = ? AND movie_id = ? AND user_id = ?', (code, mid, uid))
        conn.execute('DELETE FROM matches WHERE room_code = ? AND movie_id = ? AND status = "active" AND plex_id = ?', (code, mid, plex_id))
    return jsonify({'status': 'undone'})



@app.route('/proxy')
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



@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('data', 'sw.js')

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)


init_db()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5005)
