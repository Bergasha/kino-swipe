from flask import Flask, send_from_directory, jsonify, request, session, Response, render_template
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, os, random, requests, json

app = Flask(__name__)
# Fixes headers for your Synology Reverse Proxy
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
app.secret_key = os.getenv('FLASK_SECRET', 'KinoSwipe_2026_Default_Key')

# Standardized Paths
DB_PATH = '/app/data/kinoswipe.db'
PLEX_URL = os.getenv('PLEX_URL', '').rstrip('/')
ADMIN_TOKEN = os.getenv('PLEX_TOKEN')
CLIENT_ID = 'KinoSwipe-Bergasha-2026'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS rooms (pairing_code TEXT PRIMARY KEY, movie_data TEXT, ready INTEGER)')
        conn.execute('CREATE TABLE IF NOT EXISTS swipes (room_code TEXT, movie_id TEXT, user_id TEXT, direction TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS matches (room_code TEXT, movie_id TEXT, title TEXT, thumb TEXT)')

# --- STANDARD ROUTING ---

@app.route('/')
def index(): 
    return render_template('index.html')

@app.route('/manifest.json')
def serve_manifest(): 
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def serve_sw(): 
    return send_from_directory('.', 'sw.js')

@app.route('/static/<path:path>')
def serve_static(path): 
    return send_from_directory('static', path)

# --- PLEX & ROOM LOGIC ---

@app.route('/auth/plex-url')
def get_plex_url():
    REDIRECT_URL = f"{request.scheme}://{request.host}"
    headers = {'X-Plex-Product': 'KinoSwipe', 'X-Plex-Client-Identifier': CLIENT_ID, 'Accept': 'application/json'}
    try:
        res = requests.post('https://plex.tv/api/v2/pins?strong=true', headers=headers).json()
        auth_url = f"https://app.plex.tv/auth/#!?clientID={CLIENT_ID}&code={res['code']}&context%5Bdevice%5D%5Bproduct%5D=KinoSwipe&forwardUrl={REDIRECT_URL}"
        session['pending_pin_id'] = res['id']
        return jsonify({'auth_url': auth_url})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/auth/check-returned-pin')
def check_pin():
    pin_id = session.get('pending_pin_id')
    if not pin_id: return jsonify({'authToken': None})
    headers = {'X-Plex-Client-Identifier': CLIENT_ID, 'Accept': 'application/json'}
    res = requests.get(f"https://plex.tv/api/v2/pins/{pin_id}", headers=headers).json()
    token = res.get('authToken')
    if token: session.pop('pending_pin_id', None)
    return jsonify({'authToken': token})

@app.route('/watchlist/add', methods=['POST'])
def add_to_watchlist():
    data = request.json
    movie_id = data.get('movie_id')
    token = request.headers.get('X-Plex-Token')
    if not token or not movie_id:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        plex = PlexServer(PLEX_URL, ADMIN_TOKEN)
        item = plex.fetchItem(int(movie_id))
        
        account = MyPlexAccount(token=token)
        account.addToWatchlist(item)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/plex/server-info')
def get_server_info():
    try:
        plex = PlexServer(PLEX_URL, ADMIN_TOKEN)
        return jsonify({
            'machineIdentifier': plex.machineIdentifier,
            'name': plex.friendlyName
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/room/create', methods=['POST'])
def create_room():
    pairing_code = str(random.randint(1000, 9999))
    plex = PlexServer(PLEX_URL, ADMIN_TOKEN)
    random_movies = plex.library.section('Movies').search(libtype='movie', sort='random', maxresults=100)
    
    movie_list = []
    for m in random_movies:
        # Convert ms to "1h 45m" format
        runtime_str = ""
        if m.duration:
            hrs = m.duration // 3600000
            mins = (m.duration % 3600000) // 60000
            runtime_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"

        movie_list.append({
            'id': str(m.ratingKey), 
            'title': m.title, 
            'summary': m.summary, 
            'thumb': f"/proxy?path={m.thumb}",
            'rating': m.audienceRating or m.rating,
            'duration': runtime_str
        })
    
    with get_db() as conn:
        conn.execute('INSERT INTO rooms (pairing_code, movie_data, ready) VALUES (?, ?, ?)', (pairing_code, json.dumps(movie_list), 0))
    session['active_room'] = pairing_code
    session['my_user_id'] = 'host_' + str(random.randint(1, 999))
    return jsonify({'pairing_code': pairing_code})

@app.route('/room/join', methods=['POST'])
def join_room():
    code = request.json.get('code')
    with get_db() as conn:
        room = conn.execute('SELECT * FROM rooms WHERE pairing_code = ?', (code,)).fetchone()
        if room:
            conn.execute('UPDATE rooms SET ready = 1 WHERE pairing_code = ?', (code,))
            session['active_room'] = code
            session['my_user_id'] = 'guest_' + str(random.randint(1, 999))
            return jsonify({'status': 'success'})
    return jsonify({'error': 'Invalid Code'}), 404

@app.route('/room/status')
def room_status():
    code = session.get('active_room')
    if not code: return jsonify({'ready': False})
    with get_db() as conn:
        room = conn.execute('SELECT ready FROM rooms WHERE pairing_code = ?', (code,)).fetchone()
        return jsonify({'ready': bool(room['ready']) if room else False})

@app.route('/room/swipe', methods=['POST'])
def swipe():
    code = session.get('active_room')
    uid = session.get('my_user_id')
    data = request.json
    mid = str(data.get('movie_id'))
    direction = data.get('direction')
    if not code: return jsonify({'match': False})
    with get_db() as conn:
        conn.execute('INSERT INTO swipes (room_code, movie_id, user_id, direction) VALUES (?, ?, ?, ?)', (code, mid, uid, direction))
        if direction == 'right':
            others = conn.execute('SELECT user_id FROM swipes WHERE room_code = ? AND movie_id = ? AND direction = "right" AND user_id != ?', (code, mid, uid)).fetchall()
            if others:
                conn.execute('INSERT OR IGNORE INTO matches (room_code, movie_id, title, thumb) VALUES (?, ?, ?, ?)', (code, mid, data.get('title'), data.get('thumb')))
                return jsonify({'match': True, 'title': data.get('title'), 'thumb': data.get('thumb')})
    return jsonify({'match': False})

@app.route('/matches')
def get_matches():
    code = session.get('active_room')
    if not code: return jsonify([])
    with get_db() as conn:
        rows = conn.execute('SELECT title, thumb, movie_id FROM matches WHERE room_code = ?', (code,)).fetchall()
        return jsonify([dict(row) for row in rows])

@app.route('/matches/delete', methods=['POST'])
def delete_match():
    code = session.get('active_room')
    mid = str(request.json.get('movie_id'))
    with get_db() as conn:
        conn.execute('DELETE FROM matches WHERE room_code = ? AND movie_id = ?', (code, mid))
    return jsonify({'status': 'deleted'})

@app.route('/movies')
def get_movies():
    code = session.get('active_room')
    with get_db() as conn:
        room = conn.execute('SELECT movie_data FROM rooms WHERE pairing_code = ?', (code,)).fetchone()
        return Response(room['movie_data'], mimetype='application/json') if room else jsonify([])

@app.route('/proxy')
def proxy():
    path = request.args.get('path')
    res = requests.get(f"{PLEX_URL}{path}?X-Plex-Token={ADMIN_TOKEN}", stream=True)
    return Response(res.content, content_type=res.headers['Content-Type'])

@app.route('/room/quit', methods=['POST'])
def quit_room():
    code = session.get('active_room')
    if code:
        with get_db() as conn:
            conn.execute('DELETE FROM rooms WHERE pairing_code = ?', (code,))
            conn.execute('DELETE FROM swipes WHERE room_code = ?', (code,))
            conn.execute('DELETE FROM matches WHERE room_code = ?', (code,))
        session.clear()
    return jsonify({'status': 'session_ended'})

@app.route('/undo', methods=['POST'])
def undo_swipe():
    code = session.get('active_room')
    uid = session.get('my_user_id')
    mid = str(request.json.get('movie_id'))
    with get_db() as conn:
        conn.execute('DELETE FROM swipes WHERE room_code = ? AND movie_id = ? AND user_id = ?', (code, mid, uid))
        conn.execute('DELETE FROM matches WHERE room_code = ? AND movie_id = ?', (code, mid))
    return jsonify({'status': 'undone'})

if __name__ == "__main__":
    init_db()
    app.run(host='0.0.0.0', port=5005)

