import os
import json
import requests
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount
from plexapi.exceptions import NotFound

PLEX_URL = os.getenv('PLEX_URL', '').rstrip('/')
ADMIN_TOKEN = os.getenv('PLEX_TOKEN')
TMDB_API_KEY = os.getenv('TMDB_API_KEY')
CLIENT_ID = 'KinoSwipe-Bergasha-2026'

JELLYFIN_URL = os.getenv('JELLYFIN_URL', '').rstrip('/')
JELLYFIN_API_KEY = os.getenv('JELLYFIN_API_KEY', '')

APP_LOCALE = os.getenv('APP_LOCALE', 'en').lower()

PLEX_LIBRARY_BY_LOCALE = {
    'en': 'Movies',
    'de': 'Filme',
}

plex_ready = bool(PLEX_URL and ADMIN_TOKEN)
jellyfin_ready = bool(JELLYFIN_URL and JELLYFIN_API_KEY)

_plex_genre_cache = None
_plex_instance = None
_jellyfin_genre_cache = None

def get_plex(user_token=None):
    token = user_token or ADMIN_TOKEN
    if not token:
        raise ValueError("No Plex token provided and ADMIN_TOKEN is missing.")
    
    if token == ADMIN_TOKEN:
        global _plex_instance
        if _plex_instance is not None:
            return _plex_instance
        _plex_instance = PlexServer(PLEX_URL, ADMIN_TOKEN)
        return _plex_instance
        
    try:
        return PlexServer(PLEX_URL, token)
    except Exception:
        try:
            admin_server = get_plex(ADMIN_TOKEN)
            target_uuid = admin_server.machineIdentifier
            
            account = MyPlexAccount(token=token)
            for resource in account.resources():
                if resource.clientIdentifier == target_uuid or resource.name == admin_server.friendlyName:
                    return PlexServer(PLEX_URL, resource.accessToken)
            
            raise NotFound("Could not find matching local server resource for home profile token.")
        except Exception:
            return PlexServer(PLEX_URL, token)

def reset_plex():
    global _plex_instance
    _plex_instance = None

def get_plex_movie_section(plex):
    library_name = PLEX_LIBRARY_BY_LOCALE.get(APP_LOCALE, PLEX_LIBRARY_BY_LOCALE['en'])
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

GENRE_CACHE_TTL = 86400  # 24 hours

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

def _jf_headers():
    return {
        'X-Emby-Token': JELLYFIN_API_KEY,
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
            'EnableImages': 'false',
            'EnableUserData': 'false',
        }
        r = requests.get(f"{JELLYFIN_URL}/Genres", headers=_jf_headers(), params=params, timeout=10)
        r.raise_for_status()
        genres = sorted(g['Name'] for g in r.json().get('Items', []))
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
        url = f"{JELLYFIN_URL}/Users/{user_id}/Items"
        headers = {"X-Emby-Token": user_token, "Content-Type": "application/json"}
    else:
        url = f"{JELLYFIN_URL}/Items"
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
    item = items[0]
    if item.get('CommunityRating') is not None:
        item['CommunityRating'] = round(item['CommunityRating'], 1)
    return item

def tmdb_search(title, year, movie_id=None, backend=None):
    """Search TMDB for a movie ID. Caches results in tmdb_cache keyed by (backend, movie_id)."""
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


    tmdb_id = None
    base = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={requests.utils.quote(title)}"
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
