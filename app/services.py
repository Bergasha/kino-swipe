import json
import requests
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount
from plexapi.exceptions import NotFound

from app import config

CLIENT_ID = 'KinoSwipe-Bergasha-2026'

PLEX_LIBRARY_BY_LOCALE = {
    'en': 'Movies',
    'de': 'Filme',
}


def plex_url():
    return (config.get('PLEX_URL') or '').rstrip('/')


def plex_token():
    return config.get('PLEX_TOKEN')


def jellyfin_url():
    return (config.get('JELLYFIN_URL') or '').rstrip('/')


def jellyfin_key():
    return config.get('JELLYFIN_API_KEY') or ''


def tmdb_key():
    return config.get('TMDB_API_KEY')


def app_locale():
    return (config.get('APP_LOCALE') or 'en').lower()


def is_plex_ready():
    return bool(plex_url() and plex_token())


def is_jellyfin_ready():
    return bool(jellyfin_url() and jellyfin_key())


def is_tmdb_ready():
    return bool(tmdb_key())


def create_plex_pin_auth(forward_template):
    headers = {'X-Plex-Product': 'KinoSwipe', 'X-Plex-Client-Identifier': CLIENT_ID, 'Accept': 'application/json'}
    res = requests.post('https://plex.tv/api/v2/pins?strong=true', headers=headers, timeout=10).json()
    forward = forward_template.format(pin_id=res['id'])
    auth_url = (
        f"https://app.plex.tv/auth/#!?clientID={CLIENT_ID}"
        f"&code={res['code']}"
        f"&context%5Bdevice%5D%5Bproduct%5D=KinoSwipe"
        f"&forwardUrl={requests.utils.quote(forward, safe='')}"
    )
    return res['id'], auth_url


_plex_genre_cache = None
_plex_instance = None
_jellyfin_genre_cache = None


def _clear_backend_caches(backend):
    from app.database import db_session
    with db_session() as conn:
        conn.execute('DELETE FROM library_cache WHERE backend = ?', (backend,))
        conn.execute('DELETE FROM genre_cache WHERE backend = ?', (backend,))


def _on_config_change(changed):
    global _plex_genre_cache, _jellyfin_genre_cache
    if changed & {'PLEX_URL', 'PLEX_TOKEN', 'APP_LOCALE'}:
        reset_plex()
        _plex_genre_cache = None
        _clear_backend_caches('plex')
    if changed & {'JELLYFIN_URL', 'JELLYFIN_API_KEY'}:
        _jellyfin_genre_cache = None
        _clear_backend_caches('jellyfin')
    if 'TMDB_API_KEY' in changed:
        from app.database import db_session
        with db_session() as conn:
            conn.execute('DELETE FROM tmdb_cache WHERE tmdb_id IS NULL')


config.on_change(_on_config_change)


def get_plex(user_token=None):
    admin_token = plex_token()
    token = user_token or admin_token
    if not token:
        raise ValueError("No Plex token provided and the admin token is missing.")

    if token == admin_token:
        global _plex_instance
        if _plex_instance is not None:
            return _plex_instance
        _plex_instance = PlexServer(plex_url(), admin_token)
        return _plex_instance

    try:
        return PlexServer(plex_url(), token)
    except Exception:
        try:
            admin_server = get_plex(admin_token)
            target_uuid = admin_server.machineIdentifier

            account = MyPlexAccount(token=token)
            for resource in account.resources():
                if resource.clientIdentifier == target_uuid or resource.name == admin_server.friendlyName:
                    return PlexServer(plex_url(), resource.accessToken)

            raise NotFound("Could not find matching local server resource for home profile token.")
        except Exception:
            return PlexServer(plex_url(), token)

def reset_plex():
    global _plex_instance
    _plex_instance = None

def get_plex_movie_section(plex):
    library_name = PLEX_LIBRARY_BY_LOCALE.get(app_locale(), PLEX_LIBRARY_BY_LOCALE['en'])
    try:
        return plex.library.section(library_name)
    except NotFound:
        pass

    for name in PLEX_LIBRARY_BY_LOCALE.values():
        try:
            return plex.library.section(name)
        except NotFound:
            continue

    for section in plex.library.sections():
        if section.type == 'movie':
            return section

    raise NotFound('No Plex movie library found')

GENRE_CACHE_TTL = 86400

def get_plex_genres():
    global _plex_genre_cache
    if _plex_genre_cache is not None:
        return _plex_genre_cache

    from app.database import db_session
    import time

    with db_session() as conn:
        row = conn.execute(
            'SELECT genre_data, updated_at FROM genre_cache WHERE backend = ?', ('plex',)
        ).fetchone()
        if row and (time.time() - row['updated_at']) < GENRE_CACHE_TTL:
            _plex_genre_cache = json.loads(row['genre_data'])
            return _plex_genre_cache

    try:
        plex = get_plex()
        section = get_plex_movie_section(plex)
        genres = sorted({g.title for g in section.listFilterChoices(field='genre')})
        display = ["Sci-Fi" if g == "Science Fiction" else g for g in genres]
        _plex_genre_cache = display
        with db_session() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO genre_cache (backend, genre_data, updated_at) VALUES (?, ?, ?)',
                ('plex', json.dumps(display), time.time())
            )
        return display
    except Exception:
        with db_session() as conn:
            row = conn.execute(
                'SELECT genre_data FROM genre_cache WHERE backend = ?', ('plex',)
            ).fetchone()
            if row:
                return json.loads(row['genre_data'])
        return []

def fetch_plex_movies(genre_name=None, user_token=None):
    try:
        plex = get_plex(user_token=user_token)
        movie_section = get_plex_movie_section(plex)
    except Exception:
        if not user_token:
            reset_plex()
        plex = get_plex(user_token=user_token)
        movie_section = get_plex_movie_section(plex)
    search_genre = "Science Fiction" if genre_name == "Sci-Fi" else genre_name

    if genre_name == "Recently Added":
        movies = movie_section.search(libtype='movie', sort='addedAt:desc', maxresults=100)
    elif search_genre and search_genre != "All":
        movies = movie_section.search(libtype='movie', genre=search_genre)
        if not movies and search_genre != genre_name:
            movies = movie_section.search(libtype='movie', genre=genre_name)
    else:
        movies = movie_section.search(libtype='movie')

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

_JF_CLIENT_PARAMS = f'Client="KinoSwipe", Device="Browser", DeviceId="{CLIENT_ID}", Version="1.0.0"'


def _jf_client_auth():
    return f'MediaBrowser {_JF_CLIENT_PARAMS}'


def _jf_auth_header(token):
    return f'MediaBrowser Token="{token}", {_JF_CLIENT_PARAMS}'


def _jf_headers(token=None):
    return {
        'Authorization': _jf_auth_header(token or jellyfin_key()),
        'Content-Type': 'application/json',
    }

def get_jellyfin_genres():
    global _jellyfin_genre_cache
    if _jellyfin_genre_cache is not None:
        return _jellyfin_genre_cache

    from app.database import db_session
    import time

    with db_session() as conn:
        row = conn.execute(
            'SELECT genre_data, updated_at FROM genre_cache WHERE backend = ?', ('jellyfin',)
        ).fetchone()
        if row and (time.time() - row['updated_at']) < GENRE_CACHE_TTL:
            _jellyfin_genre_cache = json.loads(row['genre_data'])
            return _jellyfin_genre_cache

    try:
        params = {
            'IncludeItemTypes': 'Movie',
            'Recursive': 'true',
            'Fields': 'Genres',
            'EnableImages': 'false',
            'EnableUserData': 'false',
        }
        r = requests.get(f"{jellyfin_url()}/Items", headers=_jf_headers(), params=params, timeout=10)
        r.raise_for_status()
        
        movie_genres = set()
        for item in r.json().get('Items', []):
            for genre in item.get('Genres', []):
                if genre:
                    movie_genres.add(genre)
                    
        genres = sorted(list(movie_genres))
        _jellyfin_genre_cache = genres
        with db_session() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO genre_cache (backend, genre_data, updated_at) VALUES (?, ?, ?)',
                ('jellyfin', json.dumps(genres), time.time())
            )
        return genres
    except Exception:
        with db_session() as conn:
            row = conn.execute(
                'SELECT genre_data FROM genre_cache WHERE backend = ?', ('jellyfin',)
            ).fetchone()
            if row:
                return json.loads(row['genre_data'])
        return []

def fetch_jellyfin_movies(genre_name=None, user_id=None, user_token=None):
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

    if user_id and user_token:
        url = f"{jellyfin_url()}/Users/{user_id}/Items"
        headers = _jf_headers(user_token)
    else:
        url = f"{jellyfin_url()}/Items"
        headers = _jf_headers()

    r = requests.get(url, headers=headers, params=params, timeout=15)
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
        f"{jellyfin_url()}/Items",
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
    item = items[0]
    if item.get('CommunityRating') is not None:
        item['CommunityRating'] = round(item['CommunityRating'], 1)
    return item

def tmdb_search(title, year, movie_id=None, backend=None):
    from app.database import db_session
    import time

    if movie_id and backend:
        with db_session() as conn:
            row = conn.execute(
                'SELECT tmdb_id FROM tmdb_cache WHERE backend = ? AND movie_id = ?',
                (backend, str(movie_id))
            ).fetchone()
            if row is not None:
                return row['tmdb_id']

    api_key = tmdb_key()
    if not api_key:
        return None

    tmdb_id = None
    base = f"https://api.themoviedb.org/3/search/movie?api_key={api_key}&query={requests.utils.quote(title)}"
    try:
        if year:
            r = requests.get(f"{base}&year={year}", timeout=10).json()
            if r.get('results'):
                tmdb_id = r['results'][0]['id']
        if tmdb_id is None:
            r = requests.get(base, timeout=10).json()
            if r.get('results'):
                tmdb_id = r['results'][0]['id']
    except Exception:
        pass

    if movie_id and backend:
        with db_session() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO tmdb_cache (backend, movie_id, tmdb_id, updated_at) VALUES (?, ?, ?, ?)',
                (backend, str(movie_id), tmdb_id, time.time())
            )

    return tmdb_id
