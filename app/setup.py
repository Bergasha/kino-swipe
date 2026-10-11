import functools
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
from flask import Blueprint, abort, jsonify, render_template, request, session

from app import config
from app.services import (
    CLIENT_ID, app_locale, create_plex_pin_auth, is_jellyfin_ready, is_plex_ready,
    is_tmdb_ready, jellyfin_url, plex_token, plex_url, _jf_client_auth, _jf_headers
)

setup_bp = Blueprint('setup', __name__)

ADMIN_SESSION_SECONDS = 6 * 3600
MAX_FAILURES = 5
LOCK_SECONDS = 300
PENDING_SECONDS = 900
MAX_PENDING = 200

_failures = {}
_failures_lock = threading.Lock()
_pending = {}
_pending_lock = threading.Lock()


def _claimed():
    return is_plex_ready() or is_jellyfin_ready()


def _is_admin():
    return session.get('admin_until', 0) > time.time()


def _can_manage():
    return _is_admin() or not _claimed()


def _grant_admin():
    session['admin_until'] = time.time() + ADMIN_SESSION_SECONDS


def admin_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not _can_manage():
            return jsonify({'error': 'Sign in as the owner of your media server to change settings.'}), 401
        return fn(*args, **kwargs)
    return wrapper


def _body():
    if not request.is_json:
        abort(415)
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _client_ip():
    return request.remote_addr or 'unknown'


def _throttled():
    now = time.time()
    with _failures_lock:
        recent = [t for t in _failures.get(_client_ip(), []) if now - t < LOCK_SECONDS]
        _failures[_client_ip()] = recent
        return len(recent) >= MAX_FAILURES


def _record_failure():
    with _failures_lock:
        _failures.setdefault(_client_ip(), []).append(time.time())


def _clear_failures():
    with _failures_lock:
        _failures.pop(_client_ip(), None)


def _too_many():
    return jsonify({'error': 'Too many failed attempts. Try again in a few minutes.'}), 429


def _pending_entry(create=False):
    sid = session.get('setup_sid')
    if not sid and create:
        sid = secrets.token_urlsafe(16)
        session['setup_sid'] = sid
    if not sid:
        return None
    now = time.time()
    with _pending_lock:
        for key in [k for k, v in _pending.items() if v.get('expires', 0) < now]:
            del _pending[key]
        if sid not in _pending and create:
            while len(_pending) >= MAX_PENDING:
                del _pending[min(_pending, key=lambda k: _pending[k].get('expires', 0))]
            _pending[sid] = {}
        entry = _pending.get(sid)
        if entry is not None:
            entry['expires'] = now + PENDING_SECONDS
        return entry


def _locked(name):
    return jsonify({
        'error': f'{name} is set with environment variables on the container. Remove them to manage {name} here.'
    }), 409


def _plex_locked():
    return config.is_env('PLEX_URL') or config.is_env('PLEX_TOKEN')


def _jellyfin_locked():
    return config.is_env('JELLYFIN_URL') or config.is_env('JELLYFIN_API_KEY')


def _normalize_url(value):
    value = (value or '').strip().rstrip('/')
    if not value:
        return ''
    if not re.match(r'^https?://', value, re.I):
        value = 'http://' + value
    parsed = urlparse(value)
    return value if parsed.netloc else ''


@setup_bp.after_request
def _no_store(response):
    if request.path.startswith('/setup'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@setup_bp.route('/setup')
def setup_page():
    return render_template('setup.html')


@setup_bp.route('/setup/api/lock', methods=['POST'])
def lock():
    session.pop('admin_until', None)
    entry = _pending_entry()
    if entry is not None:
        entry.pop('plex_token', None)
        entry.pop('pin_id', None)
    return jsonify({'ok': True})


@setup_bp.route('/setup/api/state')
def state():
    result = {'admin': _can_manage(), 'claimed': _claimed()}
    if not result['admin']:
        result['signin'] = {'plex': is_plex_ready(), 'jellyfin': is_jellyfin_ready()}
        return jsonify(result)
    result.update({
        'plex': {
            'ready': is_plex_ready(),
            'url': plex_url(),
            'name': config.get('PLEX_SERVER_NAME'),
            'locked': _plex_locked(),
        },
        'jellyfin': {
            'ready': is_jellyfin_ready(),
            'url': jellyfin_url(),
            'name': config.get('JELLYFIN_SERVER_NAME'),
            'locked': _jellyfin_locked(),
        },
        'tmdb': {'ready': is_tmdb_ready(), 'locked': config.is_env('TMDB_API_KEY')},
        'locale': {'value': app_locale(), 'locked': config.is_env('APP_LOCALE')},
    })
    return jsonify(result)


def _machine_id(response):
    try:
        return (response.json().get('MediaContainer') or {}).get('machineIdentifier')
    except ValueError:
        match = re.search(r'machineIdentifier="([^"]+)"', response.text)
        return match.group(1) if match else None


def _probe_plex(uri, expected_id):
    try:
        response = requests.get(f'{uri}/identity', headers={'Accept': 'application/json'}, timeout=4)
        if response.status_code != 200:
            return False
        machine = _machine_id(response)
        return not expected_id or not machine or machine == expected_id
    except Exception:
        return False


def _plex_resources(token):
    headers = {'X-Plex-Token': token, 'X-Plex-Client-Identifier': CLIENT_ID, 'Accept': 'application/json'}
    response = requests.get(
        'https://plex.tv/api/v2/resources',
        params={'includeHttps': 1, 'includeRelay': 0, 'includeIPv6': 0},
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    return [
        r for r in response.json()
        if 'server' in (r.get('provides') or '').split(',') and r.get('owned')
    ]


def _discover_plex_servers(token):
    servers = []
    for resource in _plex_resources(token):
        connections = []
        for conn in resource.get('connections') or []:
            uri = (conn.get('uri') or '').rstrip('/')
            if uri and not conn.get('relay'):
                connections.append({'uri': uri, 'local': bool(conn.get('local'))})
        servers.append({
            'name': resource.get('name') or 'Plex server',
            'id': resource.get('clientIdentifier'),
            'connections': connections[:8],
        })
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = [
            (conn, pool.submit(_probe_plex, conn['uri'], server['id']))
            for server in servers for conn in server['connections']
        ]
        for conn, job in jobs:
            conn['reachable'] = job.result()
    for server in servers:
        server['connections'].sort(key=lambda c: (not c['reachable'], not c['local']))
    return servers


def _verify_plex(url, token):
    headers = {'X-Plex-Token': token, 'Accept': 'application/json'}
    try:
        response = requests.get(f'{url}/', headers=headers, timeout=8)
    except requests.exceptions.SSLError:
        raise ValueError("Couldn't verify that server's certificate. Try its plain http:// address instead.")
    except requests.RequestException:
        raise ValueError("Couldn't reach that address from the Kino-Swipe container.")
    if response.status_code == 401:
        raise ValueError('Plex rejected that token.')
    if response.status_code != 200:
        raise ValueError(f'Plex answered with HTTP {response.status_code}.')
    try:
        container = response.json().get('MediaContainer') or {}
    except ValueError:
        raise ValueError("That address doesn't look like a Plex server.")
    movie_library = False
    try:
        sections = requests.get(f'{url}/library/sections', headers=headers, timeout=8).json()
        directories = (sections.get('MediaContainer') or {}).get('Directory') or []
        movie_library = any(d.get('type') == 'movie' for d in directories)
    except Exception:
        pass
    return {
        'name': container.get('friendlyName') or 'Plex server',
        'machineId': container.get('machineIdentifier'),
        'movieLibrary': movie_library,
    }


def _configured_plex_machine_id():
    if not _plex_locked():
        stored = config.get('PLEX_MACHINE_ID')
        if stored:
            return stored
    try:
        response = requests.get(
            f'{plex_url()}/', headers={'X-Plex-Token': plex_token(), 'Accept': 'application/json'}, timeout=6
        )
        return (response.json().get('MediaContainer') or {}).get('machineIdentifier')
    except Exception:
        return None


def _plex_signin(token):
    if _throttled():
        return _too_many()
    machine = _configured_plex_machine_id()
    if not machine:
        return jsonify({'error': "Kino-Swipe couldn't work out which Plex server it is connected to right now."}), 503
    try:
        owned = {r.get('clientIdentifier') for r in _plex_resources(token)}
    except Exception:
        return jsonify({'error': "Signed in, but couldn't check your Plex servers."}), 502
    if machine not in owned:
        _record_failure()
        return jsonify({'error': "That Plex account doesn't own the server Kino-Swipe is connected to."}), 403
    _clear_failures()
    _grant_admin()
    return jsonify({'signedIn': True})


@setup_bp.route('/setup/api/plex/start', methods=['POST'])
def plex_start():
    _body()
    if not _can_manage() and not is_plex_ready():
        return jsonify({'error': "Plex isn't set up here."}), 400
    base = f'{request.scheme}://{request.host}'
    try:
        pin_id, auth_url = create_plex_pin_auth(f'{base}/setup?plex_pin={{pin_id}}')
    except Exception:
        return jsonify({'error': "Couldn't reach plex.tv. Check the container's internet access."}), 502
    _pending_entry(create=True)['pin_id'] = str(pin_id)
    return jsonify({'auth_url': auth_url})


@setup_bp.route('/setup/api/plex/pin', methods=['POST'])
def plex_pin():
    pin_id = str(_body().get('pin_id', ''))
    if not re.fullmatch(r'\d{1,20}', pin_id):
        return jsonify({'error': 'That Plex sign-in link is invalid.'}), 400
    entry = _pending_entry()
    if not entry or entry.get('pin_id') != pin_id:
        return jsonify({'error': 'That Plex sign-in link has expired. Start again.'}), 400
    headers = {'X-Plex-Client-Identifier': CLIENT_ID, 'Accept': 'application/json'}
    try:
        pin = requests.get(f'https://plex.tv/api/v2/pins/{pin_id}', headers=headers, timeout=10).json()
    except Exception:
        return jsonify({'error': "Couldn't reach plex.tv. Check the container's internet access."}), 502
    token = pin.get('authToken')
    if not token:
        return jsonify({'pending': True})
    entry.pop('pin_id', None)
    if not _can_manage():
        if not is_plex_ready():
            return jsonify({'error': "Plex isn't set up here."}), 400
        return _plex_signin(token)
    if _plex_locked():
        return _locked('Plex')
    try:
        servers = _discover_plex_servers(token)
    except Exception:
        return jsonify({'error': "Signed in, but couldn't list your Plex servers."}), 502
    entry['plex_token'] = token
    return jsonify({'servers': servers})


@setup_bp.route('/setup/api/plex/save', methods=['POST'])
@admin_required
def plex_save():
    if _plex_locked():
        return _locked('Plex')
    data = _body()
    url = _normalize_url(data.get('url'))
    token = str(data.get('token') or '').strip()
    entry = _pending_entry()
    if not token and entry:
        token = entry.get('plex_token') or ''
    if not url:
        return jsonify({'error': 'Enter your Plex server address.'}), 400
    if not token:
        return jsonify({'error': 'Connect with Plex first, or paste a Plex token.'}), 400
    try:
        info = _verify_plex(url, token)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    config.put_many({
        'PLEX_URL': url, 'PLEX_TOKEN': token,
        'PLEX_SERVER_NAME': info['name'], 'PLEX_MACHINE_ID': info['machineId'],
    })
    if entry:
        entry.pop('plex_token', None)
    _grant_admin()
    return jsonify({'ok': True, 'name': info['name'], 'movieLibrary': info['movieLibrary']})


@setup_bp.route('/setup/api/plex/disconnect', methods=['POST'])
@admin_required
def plex_disconnect():
    _body()
    if _plex_locked():
        return _locked('Plex')
    config.delete('PLEX_URL', 'PLEX_TOKEN', 'PLEX_SERVER_NAME', 'PLEX_MACHINE_ID')
    return jsonify({'ok': True})


def _jellyfin_public_info(url):
    try:
        response = requests.get(f'{url}/System/Info/Public', timeout=8)
    except requests.RequestException:
        raise ValueError(
            "Couldn't reach Jellyfin at that address from the Kino-Swipe container. "
            "If both run in Docker on the same network, use the container name, like http://jellyfin:8096."
        )
    if response.status_code != 200:
        raise ValueError(f'Jellyfin answered with HTTP {response.status_code}.')
    try:
        info = response.json()
    except ValueError:
        info = None
    if not isinstance(info, dict) or not (info.get('ServerName') or info.get('Version')):
        raise ValueError("That address doesn't look like a Jellyfin server.")
    return info


def _jellyfin_authenticate(url, username, password):
    try:
        response = requests.post(
            f'{url}/Users/AuthenticateByName',
            headers={'Authorization': _jf_client_auth(), 'Content-Type': 'application/json'},
            json={'Username': username, 'Pw': password},
            timeout=10,
        )
    except requests.RequestException:
        raise ValueError("Couldn't reach Jellyfin to sign in.")
    if response.status_code in (400, 401, 403):
        raise ValueError('Wrong username or password.')
    if response.status_code != 200:
        raise ValueError(f'Jellyfin answered with HTTP {response.status_code}.')
    body = response.json()
    token = body.get('AccessToken')
    if not token:
        raise ValueError("Jellyfin signed you in but didn't return a session.")
    policy = (body.get('User') or {}).get('Policy') or {}
    return token, bool(policy.get('IsAdministrator'))


def _jellyfin_logout(url, token):
    try:
        requests.post(f'{url}/Sessions/Logout', headers=_jf_headers(token), timeout=5)
    except Exception:
        pass


def _find_jellyfin_key(url, headers):
    response = requests.get(f'{url}/Auth/Keys', headers=headers, timeout=10)
    if response.status_code != 200:
        raise ValueError("Jellyfin wouldn't list its API keys. Create one in Dashboard > API Keys and paste it instead.")
    items = (response.json() or {}).get('Items') or []
    mine = [i for i in items if i.get('AppName') == 'KinoSwipe' and i.get('AccessToken')]
    if not mine:
        return None
    mine.sort(key=lambda i: i.get('DateCreated') or '')
    return mine[-1]['AccessToken']


def _ensure_jellyfin_key(url, token):
    headers = _jf_headers(token)
    existing = _find_jellyfin_key(url, headers)
    if existing:
        return existing
    response = requests.post(f'{url}/Auth/Keys', params={'app': 'KinoSwipe'}, headers=headers, timeout=10)
    if response.status_code not in (200, 204):
        raise ValueError("Jellyfin wouldn't create an API key. Create one in Dashboard > API Keys and paste it instead.")
    created = _find_jellyfin_key(url, headers)
    if not created:
        raise ValueError("Jellyfin created the key but didn't return it. Create one in Dashboard > API Keys and paste it instead.")
    return created


@setup_bp.route('/setup/api/signin/jellyfin', methods=['POST'])
def signin_jellyfin():
    data = _body()
    if not is_jellyfin_ready():
        return jsonify({'error': "Jellyfin isn't set up here."}), 400
    if _throttled():
        return _too_many()
    username = str(data.get('username') or '').strip()
    password = str(data.get('password') or '')
    if not username:
        return jsonify({'error': 'Enter your Jellyfin username.'}), 400
    url = jellyfin_url()
    try:
        token, is_admin = _jellyfin_authenticate(url, username, password)
    except ValueError as e:
        _record_failure()
        return jsonify({'error': str(e)}), 403
    _jellyfin_logout(url, token)
    if not is_admin:
        _record_failure()
        return jsonify({'error': "That account isn't a Jellyfin administrator."}), 403
    _clear_failures()
    _grant_admin()
    return jsonify({'ok': True})


@setup_bp.route('/setup/api/jellyfin/connect', methods=['POST'])
@admin_required
def jellyfin_connect():
    if _jellyfin_locked():
        return _locked('Jellyfin')
    data = _body()
    url = _normalize_url(data.get('url'))
    username = str(data.get('username') or '').strip()
    password = str(data.get('password') or '')
    if not url:
        return jsonify({'error': 'Enter your Jellyfin server address.'}), 400
    if not username:
        return jsonify({'error': 'Enter a Jellyfin administrator username.'}), 400
    try:
        info = _jellyfin_public_info(url)
        token, is_admin = _jellyfin_authenticate(url, username, password)
        try:
            if not is_admin:
                raise ValueError("That account isn't a Jellyfin administrator. Sign in with an admin account.")
            api_key = _ensure_jellyfin_key(url, token)
        finally:
            _jellyfin_logout(url, token)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    name = info.get('ServerName') or 'Jellyfin'
    config.put_many({'JELLYFIN_URL': url, 'JELLYFIN_API_KEY': api_key, 'JELLYFIN_SERVER_NAME': name})
    _grant_admin()
    return jsonify({'ok': True, 'name': name})


@setup_bp.route('/setup/api/jellyfin/key', methods=['POST'])
@admin_required
def jellyfin_key_save():
    if _jellyfin_locked():
        return _locked('Jellyfin')
    data = _body()
    url = _normalize_url(data.get('url'))
    api_key = str(data.get('api_key') or '').strip()
    if not url:
        return jsonify({'error': 'Enter your Jellyfin server address.'}), 400
    if not api_key:
        return jsonify({'error': 'Paste a Jellyfin API key.'}), 400
    try:
        info = _jellyfin_public_info(url)
        try:
            response = requests.get(f'{url}/System/Info', headers=_jf_headers(api_key), timeout=8)
        except requests.RequestException:
            raise ValueError("Couldn't reach Jellyfin to check the key.")
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    if response.status_code in (401, 403):
        return jsonify({'error': 'Jellyfin rejected that API key.'}), 400
    if response.status_code != 200:
        return jsonify({'error': f'Jellyfin answered with HTTP {response.status_code}.'}), 400
    try:
        name = response.json().get('ServerName')
    except ValueError:
        name = None
    name = name or info.get('ServerName') or 'Jellyfin'
    config.put_many({'JELLYFIN_URL': url, 'JELLYFIN_API_KEY': api_key, 'JELLYFIN_SERVER_NAME': name})
    _grant_admin()
    return jsonify({'ok': True, 'name': name})


@setup_bp.route('/setup/api/jellyfin/disconnect', methods=['POST'])
@admin_required
def jellyfin_disconnect():
    _body()
    if _jellyfin_locked():
        return _locked('Jellyfin')
    config.delete('JELLYFIN_URL', 'JELLYFIN_API_KEY', 'JELLYFIN_SERVER_NAME')
    return jsonify({'ok': True})


@setup_bp.route('/setup/api/tmdb', methods=['POST'])
@admin_required
def tmdb_save():
    if config.is_env('TMDB_API_KEY'):
        return _locked('TMDB')
    api_key = str(_body().get('api_key') or '').strip()
    if not api_key:
        config.delete('TMDB_API_KEY')
        return jsonify({'ok': True, 'ready': False})
    try:
        response = requests.get(
            'https://api.themoviedb.org/3/configuration', params={'api_key': api_key}, timeout=8
        )
    except requests.RequestException:
        return jsonify({'error': "Couldn't reach TMDB to check the key."}), 502
    if response.status_code == 401:
        return jsonify({'error': 'TMDB rejected that key. Use the v3 "API Key", not the Read Access Token.'}), 400
    if response.status_code != 200:
        return jsonify({'error': f'TMDB answered with HTTP {response.status_code}.'}), 502
    config.put('TMDB_API_KEY', api_key)
    return jsonify({'ok': True, 'ready': True})


@setup_bp.route('/setup/api/locale', methods=['POST'])
@admin_required
def locale_save():
    if config.is_env('APP_LOCALE'):
        return _locked('Language')
    value = str(_body().get('locale') or '').lower()
    if value not in ('en', 'de'):
        return jsonify({'error': 'Pick English or German.'}), 400
    config.put('APP_LOCALE', value)
    return jsonify({'ok': True})
