from fastapi import FastAPI, Header, HTTPException, Cookie, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional
import os, sqlite3, time, html, logging, json, hashlib, math
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB = '/app/data/metrics.db'
os.makedirs('/app/data', exist_ok=True)
conn = sqlite3.connect(DB, check_same_thread=False)
conn.execute("""
CREATE TABLE IF NOT EXISTS metrics (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 ts INTEGER NOT NULL,
 cdn_name TEXT NOT NULL,
 host TEXT NOT NULL,
 target_port INTEGER NOT NULL,
 connection_count INTEGER NOT NULL
)
""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_cdn_ts ON metrics(cdn_name, ts)")
conn.execute("""
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 username TEXT UNIQUE NOT NULL,
 hashed_password TEXT NOT NULL,
 created_at INTEGER NOT NULL
)
""")
conn.execute("""
CREATE TABLE IF NOT EXISTS domain_config (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 domain TEXT UNIQUE NOT NULL,
 cdn_name TEXT NOT NULL,
 description TEXT,
 enabled BOOLEAN DEFAULT 1,
 created_at INTEGER NOT NULL
)
""")
conn.execute("""
CREATE TABLE IF NOT EXISTS domain_hits (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 ts INTEGER NOT NULL,
 cdn_name TEXT NOT NULL,
 domain TEXT NOT NULL,
 referer TEXT,
 user_agent TEXT,
 status_code INTEGER,
 bytes_sent INTEGER,
 request_path TEXT,
 hit_count INTEGER DEFAULT 1
)
""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_domain_hits_ts_domain ON domain_hits(cdn_name, ts, domain)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_domain_hits_domain ON domain_hits(domain)")
conn.commit()

TOKEN = os.getenv('INGEST_TOKEN', 'change-me')
LEGACY_API_KEY = os.getenv('LEGACY_API_KEY', '9PsvA96mPAIO3PI9')
JWT_SECRET = os.getenv('JWT_SECRET', 'change-me-in-production')
JWT_ALGORITHM = 'HS256'
SESSION_HOURS = int(os.getenv('SESSION_HOURS', '24'))
RETENTION_DAYS = int(os.getenv('RETENTION_DAYS', '30'))
BOOTSTRAP_ADMIN_USERNAME = os.getenv('BOOTSTRAP_ADMIN_USERNAME', 'admin')
BOOTSTRAP_ADMIN_PASSWORD = os.getenv('BOOTSTRAP_ADMIN_PASSWORD', 'cdn-monitor-2026!')
AUTO_BOOTSTRAP_ADMIN = os.getenv('AUTO_BOOTSTRAP_ADMIN', 'true').lower() in ('1', 'true', 'yes', 'on')
MAP_CONFIG_FILE = os.getenv('MAP_CONFIG_FILE', '/app/data/cdn_map.json')
DOMAIN_CONFIG_FILE = os.getenv('DOMAIN_CONFIG_FILE', '/app/data/domain_config.json')

BANGLADESH_PLACES = {
    'dhaka':       {'label': 'Dhaka',        'lat': 23.8103, 'lon': 90.4125, 'landmark': 'Jatiyo Sangsad Bhaban', 'emoji': '🏛️'},
    'chattogram':  {'label': 'Chattogram',   'lat': 22.3569, 'lon': 91.7832, 'landmark': 'Patenga Sea Beach',     'emoji': '🌊'},
    'chittagong':  {'label': 'Chattogram',   'lat': 22.3569, 'lon': 91.7832, 'landmark': 'Patenga Sea Beach',     'emoji': '🌊'},
    'khulna':      {'label': 'Khulna',       'lat': 22.8456, 'lon': 89.5403, 'landmark': 'Sundarbans',            'emoji': '🌿'},
    'rajshahi':    {'label': 'Rajshahi',     'lat': 24.3745, 'lon': 88.6042, 'landmark': 'Puthia Temple Complex', 'emoji': '🛕'},
    'sylhet':      {'label': 'Sylhet',       'lat': 24.8949, 'lon': 91.8687, 'landmark': 'Ratargul Swamp Forest', 'emoji': '🌳'},
    'barishal':    {'label': 'Barishal',     'lat': 22.7010, 'lon': 90.3535, 'landmark': 'Durga Sagar Lake',      'emoji': '🏞️'},
    'barisal':     {'label': 'Barishal',     'lat': 22.7010, 'lon': 90.3535, 'landmark': 'Durga Sagar Lake',      'emoji': '🏞️'},
    'rangpur':     {'label': 'Rangpur',      'lat': 25.7439, 'lon': 89.2752, 'landmark': 'Tajhat Palace',         'emoji': '🏰'},
    'mymensingh':  {'label': 'Mymensingh',   'lat': 24.7471, 'lon': 90.4203, 'landmark': 'Zamindar Palace',       'emoji': '🏯'},
    'coxsbazar':       {'label': 'Cox’s Bazar', 'lat': 21.4272, 'lon': 92.0058, 'landmark': "World's Longest Beach", 'emoji': '🏖️'},
    "cox's bazar":     {'label': 'Cox’s Bazar', 'lat': 21.4272, 'lon': 92.0058, 'landmark': "World's Longest Beach", 'emoji': '🏖️'},
    'cumilla':     {'label': 'Cumilla',      'lat': 23.4607, 'lon': 91.1809, 'landmark': 'Mainamati Ruins',       'emoji': '🏺'},
    'comilla':     {'label': 'Cumilla',      'lat': 23.4607, 'lon': 91.1809, 'landmark': 'Mainamati Ruins',       'emoji': '🏺'},
    'bogura':      {'label': 'Bogura',       'lat': 24.8465, 'lon': 89.3773, 'landmark': 'Mahasthangarh',         'emoji': '🗿'},
    'jashore':     {'label': 'Jashore',      'lat': 23.1664, 'lon': 89.2080, 'landmark': 'Michael Madhusudan Birthplace', 'emoji': '🏡'},
    'jessore':     {'label': 'Jashore',      'lat': 23.1664, 'lon': 89.2080, 'landmark': 'Michael Madhusudan Birthplace', 'emoji': '🏡'},
    'narayanganj': {'label': 'Narayanganj',  'lat': 23.6238, 'lon': 90.5000, 'landmark': 'Panam Nagar',           'emoji': '🏘️'},
    'gazipur':     {'label': 'Gazipur',      'lat': 23.9946, 'lon': 90.4203, 'landmark': 'Bhawal National Park',  'emoji': '🌲'},
    'feni':        {'label': 'Feni',         'lat': 23.0236, 'lon': 91.3849, 'landmark': 'Shalban Vihara',        'emoji': '🕌'},
    'noakhali':    {'label': 'Noakhali',     'lat': 22.8696, 'lon': 91.0995, 'landmark': 'Gandhi Ashram',         'emoji': '🕊️'},
    'pabna':       {'label': 'Pabna',        'lat': 24.0065, 'lon': 89.2372, 'landmark': 'Hardinge Bridge',       'emoji': '🌉'},
    'dinajpur':    {'label': 'Dinajpur',     'lat': 25.6269, 'lon': 88.6378, 'landmark': 'Kantajew Temple',       'emoji': '🛕'},
}

WORLD_PLACES = {
    'london':        {'label': 'London',        'lat': 51.5074,  'lon': -0.1278,   'landmark': 'Big Ben',                'emoji': '🕐'},
    'new york':      {'label': 'New York',       'lat': 40.7128,  'lon': -74.0060,  'landmark': 'Statue of Liberty',      'emoji': '🗽'},
    'newyork':       {'label': 'New York',       'lat': 40.7128,  'lon': -74.0060,  'landmark': 'Statue of Liberty',      'emoji': '🗽'},
    'nyc':           {'label': 'New York',       'lat': 40.7128,  'lon': -74.0060,  'landmark': 'Statue of Liberty',      'emoji': '🗽'},
    'frankfurt':     {'label': 'Frankfurt',      'lat': 50.1109,  'lon': 8.6821,    'landmark': 'Römer (Old Town Hall)',   'emoji': '🏛️'},
    'sydney':        {'label': 'Sydney',         'lat': -33.8688, 'lon': 151.2093,  'landmark': 'Sydney Opera House',     'emoji': '🎭'},
    'singapore':     {'label': 'Singapore',      'lat': 1.3521,   'lon': 103.8198,  'landmark': 'Marina Bay Sands',       'emoji': '🌆'},
    'tokyo':         {'label': 'Tokyo',          'lat': 35.6762,  'lon': 139.6503,  'landmark': 'Tokyo Tower',            'emoji': '🗼'},
    'paris':         {'label': 'Paris',          'lat': 48.8566,  'lon': 2.3522,    'landmark': 'Eiffel Tower',           'emoji': '🗼'},
    'dubai':         {'label': 'Dubai',          'lat': 25.2048,  'lon': 55.2708,   'landmark': 'Burj Khalifa',           'emoji': '🏙️'},
    'amsterdam':     {'label': 'Amsterdam',      'lat': 52.3676,  'lon': 4.9041,    'landmark': 'Rijksmuseum',            'emoji': '🏛️'},
    'mumbai':        {'label': 'Mumbai',         'lat': 19.0760,  'lon': 72.8777,   'landmark': 'Gateway of India',       'emoji': '🚪'},
    'bangalore':     {'label': 'Bangalore',      'lat': 12.9716,  'lon': 77.5946,   'landmark': 'Lalbagh Botanical Garden','emoji': '🌿'},
    'los angeles':   {'label': 'Los Angeles',    'lat': 34.0522,  'lon': -118.2437, 'landmark': 'Hollywood Sign',         'emoji': '🎬'},
    'chicago':       {'label': 'Chicago',        'lat': 41.8781,  'lon': -87.6298,  'landmark': 'The Bean (Cloud Gate)',  'emoji': '🫘'},
    'toronto':       {'label': 'Toronto',        'lat': 43.6532,  'lon': -79.3832,  'landmark': 'CN Tower',               'emoji': '🗼'},
    'berlin':        {'label': 'Berlin',         'lat': 52.5200,  'lon': 13.4050,   'landmark': 'Brandenburg Gate',       'emoji': '🚪'},
    'seoul':         {'label': 'Seoul',          'lat': 37.5665,  'lon': 126.9780,  'landmark': 'Gyeongbokgung Palace',   'emoji': '🏯'},
    'hong kong':     {'label': 'Hong Kong',      'lat': 22.3193,  'lon': 114.1694,  'landmark': 'Victoria Peak',          'emoji': '🌆'},
    'hongkong':      {'label': 'Hong Kong',      'lat': 22.3193,  'lon': 114.1694,  'landmark': 'Victoria Peak',          'emoji': '🌆'},
    'moscow':        {'label': 'Moscow',         'lat': 55.7558,  'lon': 37.6173,   'landmark': 'Saint Basil\'s Cathedral','emoji': '🕌'},
    'sao paulo':     {'label': 'São Paulo',      'lat': -23.5505, 'lon': -46.6333,  'landmark': 'Ibirapuera Park',        'emoji': '🌳'},
    'johannesburg':  {'label': 'Johannesburg',   'lat': -26.2041, 'lon': 28.0473,   'landmark': 'Apartheid Museum',       'emoji': '🏛️'},
    'istanbul':      {'label': 'Istanbul',       'lat': 41.0082,  'lon': 28.9784,   'landmark': 'Hagia Sophia',           'emoji': '🕌'},
}

ALL_PLACES = {**BANGLADESH_PLACES, **WORLD_PLACES}

def area_offset(place_name: str, area_name: str, base_lat: float):
    key = f'{place_name}|{area_name}'.strip().lower().encode('utf-8')
    digest = hashlib.sha1(key).digest()
    angle = (int.from_bytes(digest[:2], 'big') / 65535.0) * (2 * math.pi)
    radius = 0.002 + (int.from_bytes(digest[2:4], 'big') / 65535.0) * 0.010
    lat_delta = math.cos(angle) * radius
    lon_scale = max(math.cos(math.radians(base_lat)), 0.25)
    lon_delta = math.sin(angle) * (radius / lon_scale)
    return lat_delta, lon_delta

def get_configured_cdns() -> set:
    raw = load_map_config_raw()
    return set(raw.keys()) if raw else set()

pwd_context = CryptContext(schemes=['argon2'], deprecated='auto')
app = FastAPI(title='CDN Monitoring System')

class MetricIn(BaseModel):
    cdn_name: str
    host: str
    target_port: int
    connection_count: int
    ts: Optional[int] = None

class LegacyMetricIn(BaseModel):
    server_id: str
    server_ip: Optional[str] = None
    connection_count: int
    timestamp: Optional[str] = None

class MapConfigIn(BaseModel):
    cdn_name: str
    place_name: Optional[str] = None
    area_name: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    ip: Optional[str] = None

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def hash_password(password):
    return pwd_context.hash(password)

def create_token(username: str, expires_hours: int = SESSION_HOURS):
    exp = datetime.utcnow() + timedelta(hours=expires_hours)
    return jwt.encode({'sub': username, 'exp': exp}, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(token: Optional[str] = Cookie(None)) -> str:
    if not token:
        raise HTTPException(status_code=401, detail='Not authenticated')
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username = payload.get('sub')
        if not username:
            raise HTTPException(status_code=401, detail='Invalid token')
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail='Invalid token')

def username_from_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get('sub')
    except JWTError:
        return None

def cleanup_old_metrics():
    cutoff = int(time.time()) - (RETENTION_DAYS * 86400)
    conn.execute('DELETE FROM metrics WHERE ts < ?', (cutoff,))
    conn.commit()
    logger.info(f'Cleaned up metrics older than {RETENTION_DAYS} days')

def bootstrap_admin_if_needed():
    if not AUTO_BOOTSTRAP_ADMIN:
        return
    row = conn.execute('SELECT COUNT(*) FROM users').fetchone()
    if row and row[0] > 0:
        return
    hashed = hash_password(BOOTSTRAP_ADMIN_PASSWORD)
    conn.execute(
        'INSERT OR REPLACE INTO users(username, hashed_password, created_at) VALUES (?, ?, ?)',
        (BOOTSTRAP_ADMIN_USERNAME, hashed, int(time.time()))
    )
    conn.commit()
    logger.warning('Bootstrapped default admin user %s', BOOTSTRAP_ADMIN_USERNAME)


@app.on_event('startup')
def startup():
    bootstrap_admin_if_needed()

def range_spec(range_key: str):
    normalized = (range_key or '24h').strip().lower()
    now = int(time.time())
    if normalized in ('24h', 'day', 'daily', 'today'):
        return {'since': now - 86400, 'bucket': 10, 'label': 'last 24 hours', 'stepLabel': '10 seconds'}
    if normalized in ('7d', 'week', 'weekly'):
        return {'since': now - 7 * 86400, 'bucket': 86400, 'label': 'last 7 days', 'stepLabel': 'day'}
    if normalized in ('30d', 'month', 'monthly'):
        return {'since': now - 30 * 86400, 'bucket': 86400, 'label': 'last 30 days', 'stepLabel': 'day'}
    return {'since': now - 86400, 'bucket': 3600, 'label': 'last 24 hours', 'stepLabel': 'hour'}

def query_history(cdn_name: str, range_key: str):
    spec = range_spec(range_key)
    rows = conn.execute(
        'SELECT (ts / ?) * ? AS bucket_ts, ROUND(AVG(connection_count)) AS connection_count, COUNT(*) AS samples '
        'FROM metrics WHERE cdn_name=? AND target_port=443 AND ts>=? GROUP BY bucket_ts ORDER BY bucket_ts',
        (spec['bucket'], spec['bucket'], cdn_name, spec['since'])
    ).fetchall()
    return spec, [{'ts': r[0], 'connection_count': int(r[1] or 0), 'samples': r[2]} for r in rows]

def query_all_series(range_key: str):
    spec = range_spec(range_key)
    cdns = get_configured_cdns()
    if not cdns:
        return spec, {}
    ph = ','.join('?' * len(cdns))
    cdn_list = list(cdns)
    rows = conn.execute(
        f"SELECT cdn_name, (ts / ?) * ? AS bucket_ts, ROUND(AVG(connection_count)) AS connection_count, COUNT(*) AS samples "
        f"FROM metrics WHERE cdn_name IN ({ph}) AND target_port=443 AND ts>=? "
        f"GROUP BY cdn_name, bucket_ts ORDER BY cdn_name, bucket_ts",
        (spec['bucket'], spec['bucket'], *cdn_list, spec['since'])
    ).fetchall()
    series = {}
    for cdn_name, bucket_ts, connection_count, samples in rows:
        series.setdefault(cdn_name, []).append({
            'ts': bucket_ts,
            'connection_count': int(connection_count or 0),
            'samples': samples,
        })
    return spec, series

def load_map_locations():
    raw = load_map_config_raw()

    resolved = []
    for cdn_name, spec in raw.items():
        place_name = None
        lat = None
        lon = None
        ip = None
        landmark = None
        emoji = None
        area_name = None
        if isinstance(spec, str):
            place_name = spec
        elif isinstance(spec, dict):
            place_name = spec.get('place_name') or spec.get('place') or spec.get('location')
            area_name = spec.get('area_name') or ''
            lat = spec.get('lat')
            lon = spec.get('lon')
            ip = spec.get('ip')

        key = (place_name or '').strip().lower()
        bd_lookup = BANGLADESH_PLACES.get(key)
        world_lookup = WORLD_PLACES.get(key)
        lookup = bd_lookup or world_lookup
        is_bd = bd_lookup is not None
        if lookup:
            place_name = lookup['label']
            landmark = lookup.get('landmark')
            emoji = lookup.get('emoji')
            base_lat = lookup['lat'] if lat is None else lat
            base_lon = lookup['lon'] if lon is None else lon
            if area_name and abs(base_lat - lookup['lat']) < 1e-9 and abs(base_lon - lookup['lon']) < 1e-9:
                dlat, dlon = area_offset(place_name or lookup['label'], area_name, base_lat)
                base_lat += dlat
                base_lon += dlon
            lat = base_lat
            lon = base_lon
        elif lat is not None:
            # manual lat/lon — check if inside BD bounds
            is_bd = (20.5 <= lat <= 26.7) and (87.9 <= (lon or 0) <= 92.8)

        resolved.append({
            'cdn_name': cdn_name,
            'place_name': place_name or '',
            'area_name': area_name or '',
            'lat': lat,
            'lon': lon,
            'ip': ip or '',
            'landmark': landmark or '',
            'emoji': emoji or '📡',
            'is_bd': is_bd,
            'resolved': bool(lat is not None and lon is not None),
        })
    return resolved

def load_map_config_raw():
    try:
        with open(MAP_CONFIG_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f) or {}
            return raw if isinstance(raw, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning('Failed to read map config: %s', exc)
        return {}

def save_map_config_raw(raw):
    os.makedirs(os.path.dirname(MAP_CONFIG_FILE), exist_ok=True)
    with open(MAP_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(raw, f, indent=2, ensure_ascii=False, sort_keys=True)

def load_domain_config():
    try:
        with open(DOMAIN_CONFIG_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f) or {}
            return raw if isinstance(raw, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning('Failed to read domain config: %s', exc)
        return {}

def get_domain_stats():
    config = load_domain_config()
    if not config:
        return []
    latest_rows = get_latest_rows_by_cdn()
    domains = []
    for domain_name, domain_info in config.items():
        if isinstance(domain_info, dict):
            cdn_name = domain_info.get('cdn_name')
            if cdn_name and cdn_name in latest_rows:
                row = latest_rows[cdn_name]
                domains.append({
                    'domain': domain_name,
                    'cdn_name': cdn_name,
                    'connection_count': row.get('connection_count', 0),
                    'ts': row.get('ts'),
                    'description': domain_info.get('description', '')
                })
    return sorted(domains, key=lambda x: x['connection_count'], reverse=True)

def query_domain_hits(domain: str, since_ts: int = None, until_ts: int = None):
    if not since_ts:
        since_ts = int(time.time()) - 86400
    if not until_ts:
        until_ts = int(time.time())
    rows = conn.execute(
        'SELECT ts, cdn_name, domain, status_code, hit_count, request_path FROM domain_hits '
        'WHERE domain=? AND ts BETWEEN ? AND ? ORDER BY ts DESC',
        (domain, since_ts, until_ts)
    ).fetchall()
    return [{'ts': r[0], 'cdn_name': r[1], 'domain': r[2], 'status_code': r[3], 'hit_count': r[4], 'request_path': r[5]} for r in rows]

def get_domain_analytics(since_ts: int = None, until_ts: int = None):
    if not since_ts:
        since_ts = int(time.time()) - 86400
    if not until_ts:
        until_ts = int(time.time())
    rows = conn.execute(
        'SELECT domain, cdn_name, SUM(hit_count) as total_hits, COUNT(*) as records, '
        'SUM(CASE WHEN status_code >= 400 THEN hit_count ELSE 0 END) as error_hits '
        'FROM domain_hits WHERE ts BETWEEN ? AND ? GROUP BY domain ORDER BY total_hits DESC',
        (since_ts, until_ts)
    ).fetchall()
    return [{'domain': r[0], 'cdn_name': r[1], 'total_hits': r[2] or 0, 'records': r[3], 'error_hits': r[4] or 0} for r in rows]

def cleanup_old_domain_hits():
    cutoff = int(time.time()) - (180 * 86400)
    conn.execute('DELETE FROM domain_hits WHERE ts < ?', (cutoff,))
    conn.commit()
    logger.info(f'Cleaned up domain hits older than 180 days')

def get_latest_rows_by_cdn():
    cdns = get_configured_cdns()
    if not cdns:
        return {}
    ph = ','.join('?' * len(cdns))
    cdn_list = list(cdns)
    rows = conn.execute(f"""
    SELECT ts, cdn_name, host, target_port, connection_count
    FROM metrics
    WHERE cdn_name IN ({ph}) AND target_port = 443
    AND (cdn_name, ts) IN (
      SELECT cdn_name, MAX(ts) FROM metrics
      WHERE cdn_name IN ({ph}) AND target_port = 443
      GROUP BY cdn_name
    )
    ORDER BY cdn_name
    """, cdn_list + cdn_list).fetchall()
    return {
        r[1]: {'ts': r[0], 'cdn_name': r[1], 'host': r[2], 'target_port': r[3], 'connection_count': r[4]}
        for r in rows
    }

def merge_latest_with_config(default_count=0):
    latest_rows = get_latest_rows_by_cdn()
    configured = load_map_locations()
    items = []
    for item in configured:
        row = latest_rows.get(item['cdn_name'])
        merged = {**item}
        if row:
            merged.update(row)
        else:
            merged.update({'ts': None, 'host': '', 'target_port': 443, 'connection_count': default_count})
        items.append(merged)
    return items

@app.get('/login', response_class=HTMLResponse)
def login_page():
    bootstrap_hint = ''
    if AUTO_BOOTSTRAP_ADMIN:
        bootstrap_hint = f"<p style='font-size:12px;opacity:.8'>First login: {html.escape(BOOTSTRAP_ADMIN_USERNAME)} / {html.escape(BOOTSTRAP_ADMIN_PASSWORD)}</p>"
    return """<!doctype html><html><head><title>CDN Monitor Login</title>
    <style>body{{font-family:Arial;background:#081018;color:#d8f7ff;padding:20px;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}}
    .login-box{{border:1px solid #1f3b4d;padding:30px;border-radius:5px;width:300px}}input{{width:100%;padding:10px;margin:10px 0;background:#0a1520;border:1px solid #1f3b4d;color:#d8f7ff;box-sizing:border-box}}
    button{{width:100%;padding:10px;margin-top:10px;background:#1f3b4d;color:#7fe8ff;border:1px solid #7fe8ff;cursor:pointer}}button:hover{{background:#2a4a5d}}
    .error{{color:#ff6b6b;margin-bottom:10px}}</style>
    </head><body><div class='login-box'><h1>CDN Monitor</h1>
    <form method='post' action='/api/login'><input type='text' name='username' placeholder='Username' required>
    <input type='password' name='password' placeholder='Password' required><button type='submit'>Login</button></form>{bootstrap_hint}</div></body></html>""".format(bootstrap_hint=bootstrap_hint)

@app.get('/api/login')
def api_login(username: str, password: str):
    user = conn.execute('SELECT hashed_password FROM users WHERE username=?', (username,)).fetchone()
    if not user or not verify_password(password, user[0]):
        logger.warning(f'Failed login attempt for user: {username}')
        raise HTTPException(status_code=401, detail='Invalid credentials')
    token = create_token(username)
    response = RedirectResponse(url='/', status_code=303)
    response.set_cookie(key='token', value=token, httponly=True, max_age=SESSION_HOURS*3600)
    logger.info(f'User logged in: {username}')
    return response

@app.get('/logout')
def logout():
    response = RedirectResponse(url='/login', status_code=303)
    response.delete_cookie('token')
    logger.info('User logged out')
    return response

@app.get('/', response_class=HTMLResponse)
def dashboard(token: Optional[str] = Cookie(None)):
    username = username_from_token(token)
    if not username:
        return RedirectResponse(url='/login', status_code=303)
    cleanup_old_metrics()
    return f"""<!doctype html><html><head><title>CDN Monitor</title>
    <style>
    body{{font-family:Arial;background:#081018;color:#d8f7ff;padding:20px;margin:0}}
    a{{color:#7fe8ff;text-decoration:none}}
    a:hover{{text-decoration:underline}}
    .wrap{{max-width:1400px;margin:0 auto}}
    .nav{{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:18px}}
    .navlinks{{display:flex;gap:14px;flex-wrap:wrap}}
    .badge{{display:inline-block;padding:4px 10px;border:1px solid #1f3b4d;border-radius:999px;background:#0a1520}}
    .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}}
    .card{{background:#0a1520;border:1px solid #1f3b4d;border-radius:12px;padding:14px}}
    .card .label{{font-size:12px;opacity:.75;margin-bottom:6px}}
    .card .value{{font-size:28px;font-weight:700}}
    .panel{{background:#0a1520;border:1px solid #1f3b4d;border-radius:12px;padding:16px;margin-top:16px}}
    .panel h2{{margin:0 0 12px 0;font-size:18px}}
    .muted{{opacity:.75}}
    .legend{{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}}
    .legend button{{background:#081018;color:#d8f7ff;border:1px solid #1f3b4d;padding:8px 10px;border-radius:999px;cursor:pointer}}
    .legend button.off{{opacity:.45;text-decoration:line-through}}
    .chart-wrap{{width:100%;background:#081018;border:1px solid #1f3b4d;border-radius:10px;padding:12px;box-sizing:border-box}}
    table{{border-collapse:collapse;width:100%}}
    td,th{{border:1px solid #1f3b4d;padding:8px 10px;text-align:left;font-size:13px}}
    th{{background:#0d1e2e;color:#7fe8ff;font-weight:600}}
    tr:hover td{{background:#0d1e2e}}
    .empty{{padding:16px 0;opacity:.75}}
    .dot-live{{display:inline-block;width:8px;height:8px;border-radius:50%;background:#27d36b;animation:dotpulse 1.4s infinite;margin-right:5px;vertical-align:middle}}
    @keyframes dotpulse{{0%{{box-shadow:0 0 0 0 rgba(39,211,107,.7)}}70%{{box-shadow:0 0 0 6px rgba(39,211,107,0)}}100%{{box-shadow:0 0 0 0 rgba(39,211,107,0)}}}}
    .status-indicator{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle;animation:statusPulse 1.2s ease-in-out infinite}}
    .status-up{{background:#27d36b}}
    .status-down{{background:#ff6b6b}}
    .status-stable{{background:#5aa8ff}}
    @keyframes statusPulse{{0%,100%{{opacity:1}}50%{{opacity:0.6}}}}
    </style>
    </head><body><div class='wrap'>
    <div class='nav'>
      <div>
        <h1 style='margin:0'>CDN Monitoring System</h1>
        <div class='muted' style='margin-top:6px'>Real-time analytics dashboard</div>
      </div>
      <div class='navlinks'>
        <a class='badge' href='/'>Home</a>
        <a class='badge' href='/domains'>Domains</a>
        <a class='badge' href='/map'>CDN MAP</a>
        <a class='badge' href='/history'>History</a>
        <a class='badge' href='/management'>Management</a>
        <a class='badge' href='/logout'>Logout ({html.escape(username)})</a>
      </div>
    </div>

    <div class='cards' id='cards'></div>
    <div style='background:#0a1520;border:1px solid #27d36b;border-radius:12px;padding:16px 24px;margin-bottom:14px;display:flex;align-items:center;gap:20px'>
      <div>
        <div style='font-size:12px;opacity:.7;margin-bottom:4px'>TOTAL CONNECTIONS (ALL CDNs)</div>
        <div id='totalCount' style='font-size:48px;font-weight:700;color:#27d36b;line-height:1'>—</div>
      </div>
      <div style='width:1px;background:#1f3b4d;align-self:stretch'></div>
      <div id='perCdnCounts' style='display:flex;gap:16px;flex-wrap:wrap'></div>
    </div>

    <div class='panel'>
      <h2>Real-time Analytics <span id='homeMeta' class='muted' style='font-size:13px;font-weight:400;margin-left:8px'></span></h2>
      <div style='display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px'>
        <div style='background:#081018;border:1px solid #1f3b4d;border-radius:10px;padding:12px;min-height:320px'>
          <div style='font-size:12px;opacity:.7;margin-bottom:8px;font-weight:600'>Connections Over Time</div>
          <div class='chart-wrap' style='height:280px;padding:0'><canvas id='homeChart'></canvas></div>
        </div>
        <div style='background:#081018;border:1px solid #1f3b4d;border-radius:10px;padding:12px;min-height:320px'>
          <div style='font-size:12px;opacity:.7;margin-bottom:8px;font-weight:600'>Peak Load Status</div>
          <div style='display:flex;align-items:center;justify-content:center;height:280px'>
            <svg id='gaugeChart' width='200' height='200' style='max-width:100%;height:auto'></svg>
          </div>
        </div>
      </div>
      <div style='display:grid;grid-template-columns:1fr 1fr;gap:16px'>
        <div style='background:#081018;border:1px solid #1f3b4d;border-radius:10px;padding:12px'>
          <div style='font-size:12px;opacity:.7;margin-bottom:8px;font-weight:600'>Top CDNs by Connections</div>
          <div id='topCdnsChart' style='height:220px'></div>
        </div>
        <div style='background:#081018;border:1px solid #1f3b4d;border-radius:10px;padding:12px'>
          <div style='font-size:12px;opacity:.7;margin-bottom:8px;font-weight:600'>Legend</div>
          <div id='legend' class='legend' style='display:flex;flex-direction:column;gap:6px;margin-top:0'></div>
        </div>
      </div>
    </div>

    <div class='panel'>
      <h2>Latest CDN Status</h2>
      <div id='latestTable'></div>
    </div>

    </div>
    <script src='https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js'></script>
    <script>
    const state = {{ hidden: {{}} }};
    const palette = ['#7fe8ff','#ff8f70','#a4ff70','#d370ff','#ffd670','#70ffd8','#ffa8d8','#9cb2ff'];
    let homeChart = null;

    function esc(text){{ const div=document.createElement('div'); div.textContent=String(text ?? ''); return div.innerHTML; }}

    function setCard(container, title, value, sub=''){{
      const card=document.createElement('div'); card.className='card';
      card.innerHTML = '<div class="label">'+esc(title)+'</div><div class="value">'+esc(value)+'</div>' + (sub ? '<div class="muted" style="margin-top:6px;font-size:12px">'+esc(sub)+'</div>' : '');
      container.appendChild(card);
    }}

    function renderCards(items){{
      const cards=document.getElementById('cards');
      cards.replaceChildren();
      const total = items.reduce((sum, item) => sum + Number(item.connection_count || 0), 0);
      setCard(cards, 'Total CDNs', items.length, 'configured nodes');
      setCard(cards, 'Total Connections', total.toLocaleString(), 'across all CDNs');
      if(items.length){{
        const top = [...items].sort((a,b)=>Number(b.connection_count||0)-Number(a.connection_count||0))[0];
        setCard(cards, 'Busiest CDN', top.cdn_name, top.connection_count + ' connections');
      }}
      items.forEach(item => setCard(cards, item.cdn_name, Number(item.connection_count||0).toLocaleString(), item.place_name || item.host || '—'));
    }}

    function renderLatestTable(items){{
      const target=document.getElementById('latestTable');
      if(!items.length){{ target.innerHTML = '<div class="empty">No data yet.</div>'; return; }}
      const table=document.createElement('table');
      const head=document.createElement('tr');
      ['CDN','IP','Connections','Last Seen'].forEach(t => {{ const th=document.createElement('th'); th.textContent=t; head.appendChild(th); }});
      table.appendChild(head);
      items.forEach(item => {{
        const tr=document.createElement('tr');
        const tsText = item.ts ? new Date(item.ts*1000).toLocaleString() : '—';
        const cells = [
          '<span class="dot-live"></span>' + esc(item.cdn_name),
          esc(item.ip || '—'),
          '<b>' + Number(item.connection_count??0).toLocaleString() + '</b>',
          esc(tsText)
        ];
        cells.forEach(html => {{ const td=document.createElement('td'); td.innerHTML=html; tr.appendChild(td); }});
        table.appendChild(tr);
      }});
      target.replaceChildren(table);
    }}

    function renderLegend(series){{
      const legend=document.getElementById('legend');
      legend.replaceChildren();
      Object.keys(series).sort().forEach((name, idx) => {{
        const btn=document.createElement('button');
        btn.innerHTML = '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:'+palette[idx%palette.length]+';margin-right:5px;vertical-align:middle"></span>' + esc(name);
        if(state.hidden[name]) btn.classList.add('off');
        btn.onclick = () => {{ state.hidden[name] = !state.hidden[name]; loadGraphs(); }};
        legend.appendChild(btn);
      }});
    }}

    function renderGauge(items){{
      const canvas = document.getElementById('gaugeChart');
      if(!canvas) return;
      const w = 180, h = 180, r = 70;
      canvas.setAttribute('viewBox', `0 0 ${{w}} ${{h}}`);
      canvas.replaceChildren();

      const total = items.reduce((s, i) => s + Number(i.connection_count || 0), 0);
      const max = items.length ? Math.max(...items.map(i => Number(i.connection_count || 0))) * 2 : 100;
      const pct = total / max;
      const clampedPct = Math.min(1, Math.max(0, pct));
      const angle = clampedPct * 240 - 120;

      const bg = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      bg.setAttribute('cx', w/2); bg.setAttribute('cy', h/2); bg.setAttribute('r', r);
      bg.setAttribute('fill', 'none'); bg.setAttribute('stroke', '#1f3b4d'); bg.setAttribute('stroke-width', '8');
      canvas.appendChild(bg);

      const color = clampedPct > 0.8 ? '#ff6b6b' : (clampedPct > 0.5 ? '#ffd670' : '#27d36b');
      const gauge = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      const startAngle = -120 * Math.PI / 180;
      const endAngle = (angle) * Math.PI / 180;
      const x1 = w/2 + r * Math.cos(startAngle);
      const y1 = h/2 + r * Math.sin(startAngle);
      const x2 = w/2 + r * Math.cos(endAngle);
      const y2 = h/2 + r * Math.sin(endAngle);
      const large = Math.abs(endAngle - startAngle) > Math.PI ? 1 : 0;
      const d = `M ${{x1}} ${{y1}} A ${{r}} ${{r}} 0 ${{large}} 1 ${{x2}} ${{y2}}`;
      gauge.setAttribute('d', d);
      gauge.setAttribute('stroke', color);
      gauge.setAttribute('stroke-width', '8');
      gauge.setAttribute('fill', 'none');
      gauge.setAttribute('stroke-linecap', 'round');
      canvas.appendChild(gauge);

      const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      text.setAttribute('x', w/2); text.setAttribute('y', h/2 + 8);
      text.setAttribute('text-anchor', 'middle');
      text.setAttribute('font-size', '32');
      text.setAttribute('font-weight', '700');
      text.setAttribute('fill', color);
      text.textContent = Math.round(clampedPct * 100) + '%';
      canvas.appendChild(text);

      const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('x', w/2); label.setAttribute('y', h/2 + 30);
      label.setAttribute('text-anchor', 'middle');
      label.setAttribute('font-size', '11');
      label.setAttribute('fill', '#7fe8ff');
      label.setAttribute('opacity', '.7');
      label.textContent = total.toLocaleString() + ' / ' + Math.round(max).toLocaleString();
      canvas.appendChild(label);
    }}

    function renderTopCdns(items){{
      const target = document.getElementById('topCdnsChart');
      if(!target) return;
      const sorted = [...items].sort((a,b) => Number(b.connection_count||0) - Number(a.connection_count||0)).slice(0, 5);
      if(!sorted.length) {{ target.innerHTML = '<div class="empty">No data</div>'; return; }}

      const max = sorted[0].connection_count || 1;
      const h = 20, gap = 35;
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '100%');
      svg.setAttribute('height', '220');
      svg.setAttribute('viewBox', '0 0 300 ' + (gap * sorted.length));

      sorted.forEach((item, idx) => {{
        const y = idx * gap;
        const width = (item.connection_count / max) * 200;
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', '60');
        rect.setAttribute('y', y + 2);
        rect.setAttribute('width', width);
        rect.setAttribute('height', h);
        rect.setAttribute('fill', palette[idx % palette.length]);
        rect.setAttribute('rx', '4');
        rect.setAttribute('opacity', '.8');
        svg.appendChild(rect);

        const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        label.setAttribute('x', '4');
        label.setAttribute('y', y + h + 4);
        label.setAttribute('font-size', '11');
        label.setAttribute('fill', '#7fe8ff');
        label.textContent = item.cdn_name;
        svg.appendChild(label);

        const count = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        count.setAttribute('x', width + 65);
        count.setAttribute('y', y + h + 4);
        count.setAttribute('font-size', '11');
        count.setAttribute('fill', '#d8f7ff');
        count.setAttribute('font-weight', '700');
        count.textContent = item.connection_count.toLocaleString();
        svg.appendChild(count);
      }});
      target.replaceChildren(svg);
    }}

    function renderHomeChart(series){{
      const canvas = document.getElementById('homeChart');
      const names = Object.keys(series).filter(n => !state.hidden[n] && series[n]?.length);
      const allTs = [...new Set(names.flatMap(n => series[n].map(p => p.ts)))].sort((a,b)=>a-b);
      const labels = allTs.map(ts => {{
        const d = new Date(ts*1000);
        return d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0');
      }});
      const datasets = names.map((name, idx) => {{
        const color = palette[idx % palette.length];
        const tsMap = Object.fromEntries((series[name]||[]).map(p=>[p.ts, p.connection_count]));
        const data = allTs.map(ts => tsMap[ts] ?? null);
        return {{
          label: name,
          data,
          borderColor: color,
          backgroundColor: color.replace(')', ', 0.08)').replace('rgb','rgba').replace('#', 'rgba(').replace(/rgba\(([0-9a-f]{{2}})([0-9a-f]{{2}})([0-9a-f]{{2}})/i, (_,r,g,b)=>`rgba(${{parseInt(r,16)}},${{parseInt(g,16)}},${{parseInt(b,16)}}`),
          borderWidth: 2.5,
          pointRadius: 3,
          pointHoverRadius: 6,
          tension: 0.4,
          fill: true,
          spanGaps: true,
        }};
      }});
      if(homeChart){{ homeChart.destroy(); }}
      homeChart = new Chart(canvas, {{
        type: 'line',
        data: {{ labels, datasets }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          interaction: {{ mode: 'index', intersect: false }},
          plugins: {{
            legend: {{ display: false }},
            tooltip: {{
              backgroundColor: 'rgba(10,21,32,0.95)',
              borderColor: '#1f3b4d',
              borderWidth: 1,
              titleColor: '#7fe8ff',
              bodyColor: '#d8f7ff',
              padding: 10,
              callbacks: {{
                label: ctx => ' ' + ctx.dataset.label + ': ' + Number(ctx.parsed.y).toLocaleString()
              }}
            }}
          }},
          scales: {{
            x: {{
              grid: {{ color: '#1f3b4d' }},
              ticks: {{ color: '#7fe8ff', maxTicksLimit: 12, font: {{ size: 11 }} }},
              border: {{ color: '#1f3b4d' }}
            }},
            y: {{
              grid: {{ color: '#1f3b4d' }},
              ticks: {{ color: '#7fe8ff', font: {{ size: 11 }}, callback: v => Number(v).toLocaleString() }},
              border: {{ color: '#1f3b4d' }},
              beginAtZero: true
            }}
          }}
        }}
      }});
    }}

    async function loadGraphs(){{
      const [latestRes, seriesRes] = await Promise.all([fetch('/api/latest'), fetch('/api/series?range=24h')]);
      const latest = await latestRes.json();
      const series = await seriesRes.json();
      const items = latest.items || [];
      const liveTotal = items.reduce((sum, item) => sum + Number(item.connection_count || 0), 0);
      document.getElementById('totalCount').textContent = liveTotal.toLocaleString();
      const perCdn = document.getElementById('perCdnCounts');
      perCdn.replaceChildren();
      items.forEach(item => {{
        const d = document.createElement('div');
        d.style.cssText = 'text-align:center';
        d.innerHTML = '<div style="font-size:11px;opacity:.7">' + esc(item.cdn_name) + '</div>'
          + '<div style="font-size:20px;font-weight:700;color:#27d36b">' + Number(item.connection_count||0).toLocaleString() + '</div>';
        perCdn.appendChild(d);
      }});
      document.getElementById('homeMeta').textContent = 'Last 24h · auto-refresh 5s';
      renderCards(items);
      renderLegend(series.series || {{}});
      renderHomeChart(series.series || {{}});
      renderGauge(items);
      renderTopCdns(items);
      renderLatestTable(items);
    }}

    loadGraphs(); setInterval(loadGraphs, 5000);
    </script></body></html>"""

@app.get('/map', response_class=HTMLResponse)
def map_page(token: Optional[str] = Cookie(None)):
    username = username_from_token(token)
    if not username:
        return RedirectResponse(url='/login', status_code=303)
    return """<!doctype html><html><head><title>CDN MAP</title>
    <meta name='viewport' content='width=device-width, initial-scale=1'>
    <link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css' integrity='sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=' crossorigin=''/>
    <style>
    *{box-sizing:border-box}
    body{font-family:Arial;background:#081018;color:#d8f7ff;margin:0;padding:16px}
    .wrap{max-width:1700px;margin:0 auto}
    .nav{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}
    .navlinks{display:flex;gap:10px;flex-wrap:wrap}
    .badge{display:inline-block;padding:4px 10px;border:1px solid #1f3b4d;border-radius:999px;background:#0a1520;color:#7fe8ff;text-decoration:none;font-size:13px}
    .maps-row{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
    @media(max-width:900px){.maps-row{grid-template-columns:1fr}}
    .map-box{border:1px solid #1f3b4d;border-radius:12px;overflow:hidden;background:#050b12}
    .map-title{background:#0a1520;padding:8px 14px;font-size:13px;font-weight:700;color:#7fe8ff;border-bottom:1px solid #1f3b4d}
    .map-el{height:520px}
    .cdn-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
    .cdn-card{background:#0a1520;border:1px solid #1f3b4d;border-radius:10px;padding:10px 12px}
    .cdn-card.live-card{border-color:#27d36b}
    .card-top{display:flex;align-items:center;gap:8px;margin-bottom:6px}
    .dot{width:10px;height:10px;border-radius:50%;background:#60707c;flex:0 0 10px}
    .dot.on{background:#27d36b;animation:glow 1.4s infinite}
    @keyframes glow{0%{box-shadow:0 0 0 0 rgba(39,211,107,.7)}70%{box-shadow:0 0 0 8px rgba(39,211,107,0)}100%{box-shadow:0 0 0 0 rgba(39,211,107,0)}}
    .card-name{font-weight:700;font-size:14px}
    .card-sub{font-size:11px;opacity:.7;line-height:1.2;margin-top:-2px;margin-bottom:6px}
    .card-count{font-size:28px;font-weight:700;color:#27d36b;line-height:1.1}
    .card-count.off{color:#60707c}
    .section-title{font-size:13px;font-weight:700;color:#7fe8ff;margin:10px 0 6px}
    .cdn-pin{display:flex;flex-direction:column;align-items:center;transform:translate(-50%,-100%)}
    .pin-card{display:flex;align-items:center;gap:4px;background:rgba(5,11,18,.92);border:1px solid #27d36b;border-radius:5px;padding:3px 7px;white-space:nowrap}
    .pin-dot{width:7px;height:7px;border-radius:50%;background:#27d36b;animation:glow 1.4s infinite;flex:0 0 7px}
    .pin-dot.off{background:#60707c;animation:none}
    .pin-text{display:flex;flex-direction:column;line-height:1.05}
    .pin-name{color:#d8f7ff;font-size:10px;font-weight:700}
    .pin-area{color:#7fe8ff;font-size:9px;opacity:.9}
    .pin-count{color:#27d36b;font-size:10px;font-weight:700;margin-left:3px}
    .pin-count.off{color:#60707c}
    .leaflet-popup-content-wrapper{background:#0a1520;color:#d8f7ff;border:1px solid #1f3b4d;border-radius:10px;box-shadow:0 4px 20px rgba(0,0,0,.7)}
    .leaflet-popup-tip{background:#0a1520}
    .leaflet-popup-content{margin:10px 14px;font-size:13px;line-height:1.6}
    .popup-name{font-size:14px;font-weight:700;color:#7fe8ff;margin-bottom:3px}
    .popup-count{font-size:20px;font-weight:700;color:#27d36b}
    </style>
    </head><body><div class='wrap'>
    <div class='nav'>
      <div><h1 style='margin:0;font-size:20px'>CDN MAP</h1></div>
      <div class='navlinks'>
        <a class='badge' href='/'>Home</a>
        <a class='badge' href='/domains'>Domains</a>
        <a class='badge' href='/map'>CDN MAP</a>
        <a class='badge' href='/history'>History</a>
        <a class='badge' href='/management'>Management</a>
        <a class='badge' href='/logout'>Logout (__USERNAME__)</a>
      </div>
    </div>

    <div class='maps-row'>
      <div class='map-box'>
        <div class='map-title'>🌍 World CDN Map</div>
        <div id='worldMap' class='map-el'></div>
      </div>
      <div class='map-box'>
        <div class='map-title'>🇧🇩 Bangladesh CDN Map</div>
        <div id='bdMap' class='map-el'></div>
      </div>
    </div>

    <div class='section-title'>🌐 All CDN Nodes</div>
    <div class='cdn-list' id='cdnList'></div>

    </div>
    <script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js' integrity='sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=' crossorigin=''></script>
    <script>
    function getCount(item){ return item.connection_count || 0; }
    function isLive(item){ return item.ts != null && (Date.now()/1000 - item.ts) < 120; }

    function pinIcon(item){
      const cnt = getCount(item);
      const live = isLive(item);
      const html = '<div class="cdn-pin">'
        + '<div class="pin-card">'
        + '<span class="pin-dot' + (live?'':' off') + '"></span>'
        + '<span class="pin-text"><span class="pin-name">' + item.cdn_name + '</span>'
        + (item.area_name ? '<span class="pin-area">' + item.area_name + '</span>' : '')
        + '</span>'
        + '<span class="pin-count' + (live?'':' off') + '">' + cnt + '</span>'
        + '</div></div>';
      return L.divIcon({className:'', html, iconSize:[1,1], iconAnchor:[0,0]});
    }

    function popupHtml(item){
      const cnt = getCount(item);
      const live = isLive(item);
      return '<div class="popup-name">' + item.cdn_name + '</div>'
        + (item.place_name ? '<div>' + item.place_name + '</div>' : '')
        + (item.area_name ? '<div style="color:#7fe8ff;font-size:12px">' + item.area_name + '</div>' : '')
        + (item.ip ? '<div style="font-family:monospace;font-size:12px;color:#7fe8ff">' + item.ip + '</div>' : '')
        + '<div class="popup-count">' + cnt + '</div>'
        + '<div style="color:' + (live?'#27d36b':'#60707c') + ';font-size:12px">' + (live?'● Live':'○ Waiting') + '</div>';
    }

    let worldMarkers=[], bdMarkers=[], worldMap, bdMap, allItems=[];

    function tileLayer(){ return L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{maxZoom:18,subdomains:'abcd',attribution:'&copy; OpenStreetMap &copy; CARTO'}); }

    function addMarkers(map, items, store){
      store.forEach(m=>map.removeLayer(m)); store.length=0;
      items.filter(x=>x.resolved).forEach(item=>{
        const m = L.marker([item.lat,item.lon],{icon:pinIcon(item)}).addTo(map);
        m.bindPopup(popupHtml(item),{maxWidth:220});
        store.push(m);
      });
    }

    function refreshMarkers(){
      addMarkers(worldMap, allItems, worldMarkers);
      addMarkers(bdMap, allItems.filter(x=>x.is_bd), bdMarkers);
    }

    function renderList(items){
      const list = document.getElementById('cdnList');
      list.replaceChildren();
      items.filter(x=>x.resolved).forEach(item=>{
        const cnt = getCount(item);
        const live = isLive(item);
        const card = document.createElement('div');
        card.className = 'cdn-card' + (live?' live-card':'');
        card.id = 'card-' + item.cdn_name;
        card.innerHTML = '<div class="card-top"><span class="dot' + (live?' on':'') + '"></span><span class="card-name">' + item.cdn_name + '</span></div>'
          + ((item.place_name || item.area_name) ? '<div class="card-sub">' + [item.place_name, item.area_name].filter(Boolean).join(' · ') + '</div>' : '')
          + '<div class="card-count' + (live?'':' off') + '" id="cnt-' + item.cdn_name + '">' + cnt + '</div>';
        list.appendChild(card);
      });
    }

    async function fetchData(){
      const r = await fetch('/api/map-config');
      const d = await r.json();
      allItems = d.items || [];
    }

    async function updateCounts(){
      await fetchData();
      allItems.forEach(item=>{
        const el = document.getElementById('cnt-' + item.cdn_name);
        if(el) el.textContent = getCount(item);
      });
      refreshMarkers();
    }

    async function init(){
      worldMap = L.map('worldMap',{zoomControl:true,worldCopyJump:true}).setView([20,0],2);
      tileLayer().addTo(worldMap);
      bdMap = L.map('bdMap',{zoomControl:true}).setView([23.8,90.4],7);
      tileLayer().addTo(bdMap);

      await fetchData();
      const resolved = allItems.filter(x=>x.resolved);
      if(resolved.length) worldMap.fitBounds(L.latLngBounds(resolved.map(x=>[x.lat,x.lon])).pad(0.2));
      renderList(allItems);
      refreshMarkers();

      setInterval(async()=>{ await updateCounts(); renderList(allItems); }, 5000);
    }
    init();
    </script></body></html>""".replace('__USERNAME__', html.escape(username))

@app.get('/management', response_class=HTMLResponse)

def management_page(token: Optional[str] = Cookie(None)):
    username = username_from_token(token)
    if not username:
        return RedirectResponse(url='/login', status_code=303)
    return """<!doctype html><html><head><title>CDN Monitor Management</title>
    <meta name='viewport' content='width=device-width, initial-scale=1'>
    <style>
    body{font-family:Arial;background:#081018;color:#d8f7ff;padding:20px;margin:0}
    a{color:#7fe8ff;text-decoration:none}
    a:hover{text-decoration:underline}
    .wrap{max-width:1400px;margin:0 auto}
    .nav{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:18px}
    .navlinks{display:flex;gap:14px;flex-wrap:wrap}
    .badge{display:inline-block;padding:4px 10px;border:1px solid #1f3b4d;border-radius:999px;background:#0a1520;color:#7fe8ff;text-decoration:none}
    .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}
    .card{background:#0a1520;border:1px solid #1f3b4d;border-radius:12px;padding:14px}
    .card .label{font-size:12px;opacity:.75;margin-bottom:6px}
    .card .value{font-size:28px;font-weight:700}
    .grid{display:grid;grid-template-columns:1fr 1.1fr;gap:14px}
    .panel{background:#0a1520;border:1px solid #1f3b4d;border-radius:12px;padding:16px}
    .panel h2{margin:0 0 12px 0;font-size:18px}
    .muted{opacity:.75}
    .small{font-size:12px;opacity:.8}
    .section{margin-top:14px}
    label{display:block;margin:10px 0 6px}
    input{width:100%;box-sizing:border-box;background:#081018;color:#d8f7ff;border:1px solid #1f3b4d;padding:10px;border-radius:6px}
    button{background:#0f2a1e;color:#7bffad;border:1px solid #2c6a44;padding:10px 14px;border-radius:8px;cursor:pointer}
    button:hover{background:#133523}
    .secondary{background:#0d2438;color:#7fe8ff;border-color:#1f3b4d}
    table{border-collapse:collapse;width:100%}
    td,th{border:1px solid #1f3b4d;padding:8px;text-align:left;vertical-align:top}
    .dot{display:inline-block;width:10px;height:10px;border-radius:999px;background:#27d36b;box-shadow:0 0 0 0 rgba(39,211,107,.7);animation:pulse 1.4s infinite}
    .dot.off{background:#4d5963;animation:none;box-shadow:none}
    @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(39,211,107,.55)}70%{box-shadow:0 0 0 12px rgba(39,211,107,0)}100%{box-shadow:0 0 0 0 rgba(39,211,107,0)}}
    .row{display:flex;align-items:center;gap:8px}
    .actions{display:flex;gap:8px;flex-wrap:wrap}
    pre{white-space:pre-wrap;background:#081018;border:1px solid #1f3b4d;border-radius:8px;padding:12px;overflow:auto}
    .hint{background:#081018;border:1px dashed #1f3b4d;border-radius:10px;padding:12px;margin-top:12px}
    </style>
    </head><body><div class='wrap'>
    <div class='nav'>
      <div>
        <h1 style='margin:0'>Management</h1>
        <div class='muted' style='margin-top:6px'>Add CDNs, place them on the map, and keep agent config in sync.</div>
      </div>
      <div class='navlinks'>
        <a class='badge' href='/'>Home</a>
        <a class='badge' href='/domains'>Domains</a>
        <a class='badge' href='/map'>CDN MAP</a>
        <a class='badge' href='/history'>History</a>
        <a class='badge' href='/management'>Management</a>
        <a class='badge' href='/logout'>Logout (__USERNAME__)</a>
      </div>
    </div>

    <div class='cards' id='summaryCards'></div>

    <div class='grid'>
      <div class='panel'>
        <h2>Add / update CDN</h2>
        <div class='small'>If a CDN is listed here but has no live count, it means no agent is sending data for that CDN_NAME yet.</div>
        <form id='cdnForm'>
          <label>CDN name</label><input id='cdnName' required placeholder='cdn2'>
          <label>Place name</label><input id='placeName' required placeholder='Dhaka'>
          <label>Area name (optional)</label><input id='areaName' placeholder='inside-country'>
          <label>IP address</label><input id='cdnIp' required placeholder='152.42.176.75'>
          <label>Latitude (optional)</label><input id='lat' type='number' step='any' placeholder='23.8103'>
          <label>Longitude (optional)</label><input id='lon' type='number' step='any' placeholder='90.4125'>
          <div class='section' style='display:flex;gap:10px;flex-wrap:wrap'>
            <button type='submit'>Save CDN</button>
          </div>
        </form>

        <div class='hint'>
          <div class='small'>Agent setup hint</div>
          <pre>CDN_NAME=cdn2
TARGET_PORT=443
SERVER_ENDPOINT=http://server:18443/api/ingest
INGEST_TOKEN=...</pre>
        </div>
      </div>

      <div class='panel'>
        <h2>Configured CDNs</h2>
        <div id='configList'></div>
      </div>
    </div>
    </div>
    <script>
    function makeCard(parent, label, value, sub=''){
      const card=document.createElement('div'); card.className='card';
      card.innerHTML = '<div class="label">'+label+'</div><div class="value">'+value+'</div>' + (sub ? '<div class="muted" style="margin-top:6px">'+sub+'</div>' : '');
      parent.appendChild(card);
    }

    async function refreshConfig(){
      const [cfgRes, latestRes] = await Promise.all([fetch('/api/map-config'), fetch('/api/latest')]);
      const cfg = await cfgRes.json();
      const latest = await latestRes.json();
      const latestMap = new Map((latest.items || []).map(x => [x.cdn_name, x]));
      const items = cfg.items || [];
      const liveItems = items.filter(item => latestMap.get(item.cdn_name) && latestMap.get(item.cdn_name).ts !== null);
      const list = document.getElementById('configList');
      const summary = document.getElementById('summaryCards');
      summary.replaceChildren();
      makeCard(summary, 'Configured', String(items.length), 'CDNs in management');
      makeCard(summary, 'Live', String(liveItems.length), 'sending metrics now');
      makeCard(summary, 'Waiting', String(Math.max(0, items.length - liveItems.length)), 'need an agent');
      makeCard(summary, 'Map pins', String(items.filter(x => x.resolved).length), 'resolved locations');

      list.replaceChildren();
      if(!items.length){
        list.innerHTML = '<div class="muted">No CDN config yet.</div>';
        return;
      }
      const table=document.createElement('table');
      const head=document.createElement('tr');
      ['Status','CDN','IP','Place','Area','Lat/Lon','Live count','Actions'].forEach(title => { const th=document.createElement('th'); th.textContent=title; head.appendChild(th); });
      table.appendChild(head);
      items.forEach(item => {
        const row=document.createElement('tr');
        const live = latestMap.get(item.cdn_name);
        const statusTd = document.createElement('td');
        const statusWrap = document.createElement('div');
        statusWrap.className = 'row';
        const statusDot = document.createElement('span');
        statusDot.className = 'dot' + ((live && live.ts !== null && Number(live.connection_count) > 0) ? '' : ' off');
        const statusLabel = document.createElement('span');
        statusLabel.textContent = (live && live.ts !== null) ? 'live' : 'waiting';
        statusWrap.append(statusDot, statusLabel);
        statusTd.appendChild(statusWrap);
        row.appendChild(statusTd);

        const cdnTd = document.createElement('td'); cdnTd.textContent = item.cdn_name; row.appendChild(cdnTd);
        const ipTd = document.createElement('td'); ipTd.textContent = item.ip || ''; row.appendChild(ipTd);
        const placeTd = document.createElement('td'); placeTd.textContent = item.place_name || ''; row.appendChild(placeTd);
        const areaTd = document.createElement('td'); areaTd.textContent = item.area_name || ''; row.appendChild(areaTd);
        const latLonTd = document.createElement('td'); latLonTd.textContent = (item.lat != null && item.lon != null) ? item.lat + ', ' + item.lon : 'unresolved'; row.appendChild(latLonTd);
        const liveTd = document.createElement('td'); liveTd.textContent = live ? String(live.connection_count) : '0'; row.appendChild(liveTd);

        const actionsTd = document.createElement('td');
        actionsTd.className = 'actions';
        const edit = document.createElement('button');
        edit.type = 'button';
        edit.textContent = 'Edit';
        edit.className = 'secondary';
        edit.onclick = () => {
          document.getElementById('cdnName').value = item.cdn_name;
          document.getElementById('cdnIp').value = item.ip || '';
          document.getElementById('placeName').value = item.place_name || '';
          document.getElementById('areaName').value = item.area_name || '';
          document.getElementById('lat').value = item.lat != null ? item.lat : '';
          document.getElementById('lon').value = item.lon != null ? item.lon : '';
          document.getElementById('cdnName').scrollIntoView({behavior:'smooth', block:'center'});
          document.getElementById('cdnName').focus();
        };
        const del = document.createElement('button');
        del.type = 'button';
        del.textContent = 'Delete';
        del.onclick = async () => {
          if(!confirm('Remove ' + item.cdn_name + '?')) return;
          await fetch('/api/map-config/' + encodeURIComponent(item.cdn_name), { method: 'DELETE' });
          refreshConfig();
        };
        actionsTd.append(edit, del);
        row.appendChild(actionsTd);
        table.appendChild(row);
      });
      list.appendChild(table);
    }

    document.getElementById('cdnForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const payload = {
        cdn_name: document.getElementById('cdnName').value.trim(),
        ip: document.getElementById('cdnIp').value.trim() || null,
        place_name: document.getElementById('placeName').value.trim() || null,
        area_name: document.getElementById('areaName').value.trim() || null,
        lat: document.getElementById('lat').value ? Number(document.getElementById('lat').value) : null,
        lon: document.getElementById('lon').value ? Number(document.getElementById('lon').value) : null,
      };
      await fetch('/api/map-config', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload),
      });
      e.target.reset();
      refreshConfig();
    });

    refreshConfig();
    </script></body></html>""".replace('__USERNAME__', html.escape(username))

@app.get('/domains', response_class=HTMLResponse)
def domains_page(token: Optional[str] = Cookie(None)):
    username = username_from_token(token)
    if not username:
        return RedirectResponse(url='/login', status_code=303)
    return f"""<!doctype html><html><head><title>Domain Hits Analytics</title>
    <style>
    body{{font-family:Arial;background:#081018;color:#d8f7ff;padding:20px;margin:0}}
    a{{color:#7fe8ff;text-decoration:none}}
    a:hover{{text-decoration:underline}}
    .wrap{{max-width:1600px;margin:0 auto}}
    .nav{{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:18px}}
    .navlinks{{display:flex;gap:14px;flex-wrap:wrap}}
    .badge{{display:inline-block;padding:4px 10px;border:1px solid #1f3b4d;border-radius:999px;background:#0a1520}}
    .panel{{background:#0a1520;border:1px solid #1f3b4d;border-radius:12px;padding:16px;margin-top:16px}}
    .panel h2{{margin:0 0 12px 0;font-size:18px}}
    .muted{{opacity:.75}}
    .controls{{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:16px}}
    input,select{{background:#081018;color:#d8f7ff;border:1px solid #1f3b4d;padding:8px 12px;border-radius:6px}}
    button{{background:#0f2a1e;color:#7bffad;border:1px solid #2c6a44;padding:8px 14px;border-radius:6px;cursor:pointer}}
    button:hover{{background:#133523}}
    .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin:16px 0}}
    .card{{background:#081018;border:1px solid #1f3b4d;border-radius:12px;padding:12px;text-align:center}}
    .card .label{{font-size:11px;opacity:.7;margin-bottom:4px}}
    .card .value{{font-size:22px;font-weight:700;color:#7fe8ff}}
    table{{border-collapse:collapse;width:100%;margin-top:12px}}
    td,th{{border:1px solid #1f3b4d;padding:10px;text-align:left;font-size:13px}}
    th{{background:#0d1e2e;color:#7fe8ff;font-weight:600}}
    tr:hover td{{background:#0d1e2e}}
    .empty{{padding:20px;text-align:center;opacity:.75}}
    .error-rate{{color:#ff6b6b;font-weight:600}}
    .status-ok{{color:#27d36b}}
    .status-error{{color:#ff6b6b}}
    </style>
    </head><body><div class='wrap'>
    <div class='nav'>
      <div>
        <h1 style='margin:0'>Domain Hits Analytics</h1>
        <div class='muted' style='margin-top:6px'>6-month historical data with date filtering</div>
      </div>
      <div class='navlinks'>
        <a class='badge' href='/'>Home</a>
        <a class='badge' href='/domains'>Domains</a>
        <a class='badge' href='/map'>CDN MAP</a>
        <a class='badge' href='/history'>History</a>
        <a class='badge' href='/management'>Management</a>
        <a class='badge' href='/logout'>Logout ({html.escape(username)})</a>
      </div>
    </div>

    <div class='panel'>
      <h2>Filter & Query</h2>
      <div class='controls'>
        <label style='margin:0'>Range:
          <select id='rangeSelect'>
            <option value='24h'>Last 24 hours</option>
            <option value='7d'>Last 7 days</option>
            <option value='30d'>Last 30 days</option>
            <option value='90d'>Last 90 days</option>
            <option value='180d'>Last 180 days</option>
          </select>
        </label>
        <label style='margin:0'>Or Custom: From <input type='date' id='fromDate'> To <input type='date' id='toDate'></label>
        <button onclick='loadAnalytics()'>Apply Filter</button>
      </div>
      <span id='filterMeta' class='muted' style='font-size:12px'></span>
    </div>

    <div class='cards' id='summaryCards'></div>

    <div class='panel'>
      <h2>Domain Analytics</h2>
      <div id='analyticsTable'></div>
    </div>

    <div class='panel'>
      <h2>HTTP Status Code Distribution</h2>
      <div style='display:grid;grid-template-columns:1fr 1fr;gap:20px'>
        <div id='statusChart' style='background:#081018;border:1px solid #1f3b4d;border-radius:10px;padding:12px;min-height:200px'></div>
        <div id='statusBreakdown' style='background:#081018;border:1px solid #1f3b4d;border-radius:10px;padding:12px'></div>
      </div>
    </div>

    </div>
    <script>
    const state = {{ range: '24h', fromTs: null, toTs: null }};

    async function getTimestampRange(){{
      const now = Math.floor(Date.now() / 1000);
      const rangeVal = document.getElementById('rangeSelect').value;
      const fromDate = document.getElementById('fromDate').value;
      const toDate = document.getElementById('toDate').value;

      if(fromDate && toDate){{
        state.fromTs = Math.floor(new Date(fromDate).getTime() / 1000);
        state.toTs = Math.floor(new Date(toDate).getTime() / 1000) + 86400;
      }} else {{
        state.toTs = now;
        const days = parseInt(rangeVal) || 1;
        state.fromTs = now - (days * 86400);
      }}
    }}

    async function loadAnalytics(){{
      await getTimestampRange();
      const from = new Date(state.fromTs * 1000).toLocaleDateString();
      const to = new Date(state.toTs * 1000).toLocaleDateString();
      document.getElementById('filterMeta').textContent = `Showing data from ${{from}} to ${{to}}`;

      const res = await fetch(`/api/domain-analytics?from_ts=${{state.fromTs}}&to_ts=${{state.toTs}}`);
      const data = await res.json();
      const analytics = data.analytics || [];
      renderSummary(analytics);
      renderTable(analytics);
      renderStatusBreakdown(analytics);
    }}

    function renderSummary(analytics){{
      const summary = document.getElementById('summaryCards');
      const totalHits = analytics.reduce((s, a) => s + (a.total_hits || 0), 0);
      const totalErrors = analytics.reduce((s, a) => s + (a.error_hits || 0), 0);
      const errorRate = totalHits ? Math.round((totalErrors / totalHits) * 100) : 0;

      summary.replaceChildren();

      const cards = [
        ['Total Hits', totalHits.toLocaleString()],
        ['Total Domains', analytics.length.toString()],
        ['Error Rate', errorRate + '%'],
        ['Success Rate', (100 - errorRate) + '%']
      ];

      cards.forEach(([label, value]) => {{
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = '<div class="label">' + label + '</div><div class="value">' + value + '</div>';
        summary.appendChild(card);
      }});
    }}

    function renderTable(analytics){{
      const table = document.getElementById('analyticsTable');
      if(!analytics.length){{ table.innerHTML = '<div class="empty">No domain hits in selected period.</div>'; return; }}

      const t = document.createElement('table');
      const head = document.createElement('tr');
      ['Domain','CDN','Total Hits','Errors','Success Rate','Error Rate'].forEach(title => {{
        const th = document.createElement('th');
        th.textContent = title;
        head.appendChild(th);
      }});
      t.appendChild(head);

      analytics.forEach(a => {{
        const errorRate = a.total_hits ? Math.round((a.error_hits / a.total_hits) * 100) : 0;
        const successRate = 100 - errorRate;
        const tr = document.createElement('tr');
        const cells = [
          a.domain,
          a.cdn_name || '—',
          a.total_hits.toLocaleString(),
          '<span class="status-error">' + a.error_hits + '</span>',
          '<span class="status-ok">' + successRate + '%</span>',
          '<span class="error-rate">' + errorRate + '%</span>'
        ];
        cells.forEach(html => {{
          const td = document.createElement('td');
          td.innerHTML = html;
          tr.appendChild(td);
        }});
        t.appendChild(tr);
      }});
      table.replaceChildren(t);
    }}

    function renderStatusBreakdown(analytics){{
      const breakdown = document.getElementById('statusBreakdown');
      const statusMap = {{}};
      analytics.forEach(a => {{
        const errorRate = a.total_hits ? Math.round((a.error_hits / a.total_hits) * 100) : 0;
        statusMap['2xx Success'] = (statusMap['2xx Success'] || 0) + (a.total_hits - a.error_hits);
        statusMap['4xx/5xx Errors'] = (statusMap['4xx/5xx Errors'] || 0) + a.error_hits;
      }});

      breakdown.replaceChildren();
      Object.entries(statusMap).forEach(([status, count]) => {{
        const div = document.createElement('div');
        div.style.cssText = 'padding:8px;border-bottom:1px solid #1f3b4d';
        const color = status.includes('Error') ? '#ff6b6b' : '#27d36b';
        div.innerHTML = '<div style="color:' + color + ';font-weight:600">' + status + '</div>'
          + '<div style="font-size:20px;font-weight:700;color:' + color + '">' + count.toLocaleString() + '</div>';
        breakdown.appendChild(div);
      }});
    }}

    // Initialize with last 24 hours
    document.getElementById('rangeSelect').addEventListener('change', loadAnalytics);
    loadAnalytics();
    </script></body></html>"""

@app.get('/history', response_class=HTMLResponse)
def history_page(token: Optional[str] = Cookie(None)):
    username = username_from_token(token)
    if not username:
        return RedirectResponse(url='/login', status_code=303)
    return f"""<!doctype html><html><head><title>CDN Monitor History</title>
    <style>
    body{{font-family:Arial;background:#081018;color:#d8f7ff;padding:20px;margin:0}}
    a{{color:#7fe8ff;text-decoration:none}}
    a:hover{{text-decoration:underline}}
    .wrap{{max-width:1400px;margin:0 auto}}
    .nav{{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:18px}}
    .navlinks{{display:flex;gap:14px;flex-wrap:wrap}}
    .badge{{display:inline-block;padding:4px 10px;border:1px solid #1f3b4d;border-radius:999px;background:#0a1520}}
    .panel{{background:#0a1520;border:1px solid #1f3b4d;border-radius:12px;padding:16px;margin-top:16px}}
    .controls{{display:flex;gap:12px;flex-wrap:wrap;align-items:center}}
    select{{background:#081018;color:#d8f7ff;border:1px solid #1f3b4d;padding:8px;border-radius:6px}}
    .chart{{width:100%;height:340px;display:block}}
    .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}}
    .card{{background:#0a1520;border:1px solid #1f3b4d;border-radius:12px;padding:14px}}
    .card .label{{font-size:12px;opacity:.75;margin-bottom:6px}}
    .card .value{{font-size:24px;font-weight:700}}
    table{{border-collapse:collapse;width:100%}}
    td,th{{border:1px solid #1f3b4d;padding:8px;text-align:left}}
    .muted{{opacity:.75}}
    .empty{{padding:16px 0;opacity:.75}}
    .live-note{{margin-top:8px;font-size:12px;opacity:.8}}
    .wave-line{{fill:none;stroke-linecap:round;stroke-linejoin:round;stroke-width:3;animation:waveFlow 1.2s ease-in-out infinite}}
    .wave-fill{{fill-opacity:0.08;animation:wavePulse 1.2s ease-in-out infinite}}
    @keyframes waveFlow{{0%{{stroke-dashoffset:0}}50%{{stroke-dashoffset:8}}100%{{stroke-dashoffset:0}}}}
    @keyframes wavePulse{{0%{{fill-opacity:0.08}}50%{{fill-opacity:0.12}}100%{{fill-opacity:0.08}}}}
    .wave-circle{{animation:pointBeat 1s cubic-bezier(0.4,0,0.6,1) infinite}}
    @keyframes pointBeat{{0%,100%{{r:3.5;opacity:.8}}50%{{r:5;opacity:1}}}}
    .wave-circle.latest{{animation:latestPulse 0.8s cubic-bezier(0.4,0,0.6,1) infinite;r:6}}
    @keyframes latestPulse{{0%,100%{{r:6}}50%{{r:8}}}}
    </style>
    </head><body><div class='wrap'>
    <div class='nav'>
      <div>
        <h1 style='margin:0'>Historical data</h1>
        <div class='muted' style='margin-top:6px'>The 24 hour view refreshes every 10 seconds and uses live 10-second buckets.</div>
      </div>
      <div class='navlinks'>
        <a class='badge' href='/'>Home</a>
        <a class='badge' href='/map'>CDN MAP</a>
        <a class='badge' href='/history'>History</a>
        <a class='badge' href='/management'>Management</a>
        <a class='badge' href='/logout'>Logout ({html.escape(username)})</a>
      </div>
    </div>

    <div class='panel'>
      <div class='controls'>
        <label>CDN <select id='cdnSelect'></select></label>
        <label>Range <select id='rangeSelect'>
          <option value='24h'>Today (24 hours)</option>
          <option value='7d'>Weekly</option>
          <option value='30d'>Monthly</option>
        </select></label>
        <span id='historyMeta' class='muted'></span>
        <span id='historyTrend' class='badge' style='border-color:#5aa8ff'>Stable</span>
      </div>
      <div class='cards' id='historyCards'></div>
      <div style='position:relative;width:100%;height:360px;background:#081018;border:1px solid #1f3b4d;border-radius:10px;overflow:hidden'>
        <svg id='historyChart' class='chart' viewBox='0 0 1200 340' preserveAspectRatio='none' style='width:100%;height:100%;display:block'></svg>
        <div id='historyChartOverlay' style='position:absolute;top:0;left:0;right:0;bottom:0;pointer-events:none'></div>
      </div>
      <div id='historyEmpty' class='empty' style='display:none'>No historical data for this selection yet.</div>
      <div class='live-note'>Live wave graph updates every 10 seconds • Green (new) • Red (dropped) • Blue (stable)</div>
    </div>

    <div class='panel'>
      <h2 style='margin-top:0'>Recent points</h2>
      <div id='historyTable'></div>
    </div>
    </div>
    <script>
    const historyState = {{ cdn: null, range: '24h', refreshing: false }};

    function esc(text){{ const div=document.createElement('div'); div.textContent=String(text ?? ''); return div.textContent; }}

    function trendFor(delta){{
      if (delta > 0) return {{ key: 'up', label: 'new connection', color: '#27d36b' }};
      if (delta < 0) return {{ key: 'down', label: 'connection dropped', color: '#ff6b6b' }};
      return {{ key: 'flat', label: 'stable', color: '#5aa8ff' }};
    }}

    function makeCard(parent, label, value, sub='', color='#7fe8ff'){{
      const card=document.createElement('div'); card.className='card'; card.style.borderColor=color;
      card.innerHTML = '<div class="label">'+esc(label)+'</div><div class="value" style="color:'+color+'">'+esc(value)+'</div>' + (sub ? '<div class="muted" style="margin-top:6px">'+esc(sub)+'</div>' : '');
      parent.appendChild(card);
    }}

    function wavePath(points, xAt, yAt){{
      if(!points.length) return '';
      let d='M ' + xAt(points[0].ts).toFixed(1) + ' ' + yAt(points[0].connection_count).toFixed(1);
      for(let i=1;i<points.length;i++){{
        const prev=points[i-1], cur=points[i];
        const x1=xAt(prev.ts), y1=yAt(prev.connection_count), x2=xAt(cur.ts), y2=yAt(cur.connection_count);
        const spread=(x2-x1) * 0.45;
        d += ' C ' + (x1 + spread).toFixed(1) + ' ' + y1.toFixed(1) + ', ' + (x2 - spread).toFixed(1) + ' ' + y2.toFixed(1) + ', ' + x2.toFixed(1) + ' ' + y2.toFixed(1);
      }}
      return d;
    }}

    function drawSingleSeries(points){{
      const svg=document.getElementById('historyChart');
      const empty=document.getElementById('historyEmpty');
      const trendBadge=document.getElementById('historyTrend');
      svg.replaceChildren();
      if(!points.length){{
        empty.style.display='block';
        trendBadge.textContent = 'Stable';
        trendBadge.style.borderColor = '#5aa8ff';
        trendBadge.style.color = '#5aa8ff';
        return;
      }}
      empty.style.display='none';
      const w=1200, h=340, padL=50, padR=18, padT=18, padB=38;
      const maxValue=Math.max(1, ...points.map(p => Number(p.connection_count || 0)));
      const minTs=points[0].ts, maxTs=points[points.length-1].ts;
      const xAt = ts => padL + ((ts - minTs) / Math.max(1, (maxTs - minTs))) * (w - padL - padR);
      const yAt = value => h - padB - ((Number(value || 0) / maxValue) * (h - padT - padB));
      const trend = points.length > 1 ? trendFor(Number(points[points.length - 1].connection_count || 0) - Number(points[points.length - 2].connection_count || 0)) : trendFor(0);
      trendBadge.textContent = trend.label.charAt(0).toUpperCase() + trend.label.slice(1);
      trendBadge.style.borderColor = trend.color;
      trendBadge.style.color = trend.color;

      for(let i=0;i<5;i++){{
        const y = padT + i * ((h - padT - padB)/4);
        const line=document.createElementNS('http://www.w3.org/2000/svg','line');
        line.setAttribute('x1', padL); line.setAttribute('x2', w-padR); line.setAttribute('y1', y); line.setAttribute('y2', y);
        line.setAttribute('stroke', '#1f3b4d'); line.setAttribute('stroke-width', '1');
        svg.appendChild(line);
      }}

      const topPath = wavePath(points, xAt, yAt);
      if(topPath){{
        const fill=document.createElementNS('http://www.w3.org/2000/svg','path');
        fill.setAttribute('d', topPath + ' L ' + xAt(points[points.length-1].ts).toFixed(1) + ' ' + (h-padB) + ' L ' + xAt(points[0].ts).toFixed(1) + ' ' + (h-padB) + ' Z');
        fill.setAttribute('fill', 'rgba(127,232,255,.08)');
        fill.setAttribute('stroke', 'none');
        fill.setAttribute('class', 'wave-fill');
        svg.appendChild(fill);

        const path=document.createElementNS('http://www.w3.org/2000/svg','path');
        path.setAttribute('d', topPath);
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', trend.color);
        path.setAttribute('class', 'wave-line');
        const pathLen = path.getTotalLength ? path.getTotalLength() : 0;
        if(pathLen) {{ path.setAttribute('stroke-dasharray', pathLen); }}
        svg.appendChild(path);
      }}

      points.forEach((point, idx) => {{
        const delta = idx ? Number(point.connection_count || 0) - Number(points[idx - 1].connection_count || 0) : 0;
        const pointTrend = trendFor(delta);
        const isLatest = idx === points.length - 1;
        const circle=document.createElementNS('http://www.w3.org/2000/svg','circle');
        circle.setAttribute('cx', xAt(point.ts));
        circle.setAttribute('cy', yAt(point.connection_count));
        circle.setAttribute('r', isLatest ? '6' : '3.5');
        circle.setAttribute('fill', isLatest ? pointTrend.color : '#d8f7ff');
        circle.setAttribute('opacity', isLatest ? '1' : '.8');
        circle.setAttribute('class', 'wave-circle' + (isLatest ? ' latest' : ''));
        const title=document.createElementNS('http://www.w3.org/2000/svg','title');
        title.textContent = point.connection_count + ' connections @ ' + new Date(point.ts*1000).toLocaleString();
        circle.appendChild(title);
        svg.appendChild(circle);
      }});

      const axis=document.createElementNS('http://www.w3.org/2000/svg','line');
      axis.setAttribute('x1', padL); axis.setAttribute('x2', w-padR); axis.setAttribute('y1', h-padB); axis.setAttribute('y2', h-padB);
      axis.setAttribute('stroke', trend.color); axis.setAttribute('stroke-width', '1');
      svg.appendChild(axis);

      const latest = points[points.length - 1];
      const latestLabel=document.createElementNS('http://www.w3.org/2000/svg','text');
      latestLabel.setAttribute('x', String(Math.max(padL, xAt(latest.ts) - 10)));
      latestLabel.setAttribute('y', String(Math.max(24, yAt(latest.connection_count) - 14)));
      latestLabel.setAttribute('fill', trend.color);
      latestLabel.setAttribute('font-size', '12');
      latestLabel.textContent = String(latest.connection_count);
      svg.appendChild(latestLabel);
    }}

    function renderHistoryTable(points){{
      const target=document.getElementById('historyTable');
      if(!points.length){{ target.innerHTML = '<div class="empty">No points yet.</div>'; return; }}
      const table=document.createElement('table');
      const head=document.createElement('tr');
      ['Timestamp','Connections','Samples','Change'].forEach(title => {{ const th=document.createElement('th'); th.textContent=title; head.appendChild(th); }});
      table.appendChild(head);
      points.forEach((point, idx) => {{
        const tr=document.createElement('tr');
        const prev = points[idx - 1];
        const delta = prev ? Number(point.connection_count || 0) - Number(prev.connection_count || 0) : 0;
        const change = trendFor(delta);
        [new Date(point.ts*1000).toLocaleString(), String(point.connection_count), String(point.samples ?? 1), (delta > 0 ? '+' : '') + String(delta)].forEach((value, i) => {{ const td=document.createElement('td'); td.textContent=value; if(i === 3) td.style.color = change.color; tr.appendChild(td); }});
        table.appendChild(tr);
      }});
      target.replaceChildren(table);
    }}

    async function loadHistory(){{
      if(!historyState.cdn || historyState.refreshing) return;
      historyState.refreshing = true;
      try {{
        const [historyRes, latestRes] = await Promise.all([
          fetch('/api/history?cdn_name=' + encodeURIComponent(historyState.cdn) + '&range=' + encodeURIComponent(historyState.range)),
          fetch('/api/latest')
        ]);
        const d=await historyRes.json();
        const latestPayload = await latestRes.json();
        const latestItem = (latestPayload.items || []).find(item => item.cdn_name === historyState.cdn);
        document.getElementById('historyMeta').textContent = d.label + ' · ' + historyState.cdn + ' · ' + (d.stepLabel || 'bucketed') + ' · refreshes every 10 seconds';
        const points = d.points || [];
        const current = latestItem ? latestItem.connection_count : (points.length ? points[points.length - 1].connection_count : 'n/a');
        const max = points.length ? Math.max(...points.map(p => p.connection_count)) : 0;
        const avg = points.length ? Math.round(points.reduce((sum,p)=>sum + Number(p.connection_count||0),0) / points.length) : 0;
        const historyTrend = points.length > 1 ? trendFor(Number(points[points.length - 1].connection_count || 0) - Number(points[points.length - 2].connection_count || 0)) : trendFor(0);
        const liveTrend = latestItem && points.length ? trendFor(Number(latestItem.connection_count || 0) - Number(points[points.length - 1].connection_count || 0)) : historyTrend;
        const cards=document.getElementById('historyCards');
        cards.replaceChildren();
        makeCard(cards, 'Current', current, 'latest point', liveTrend.color);
        makeCard(cards, 'Maximum', max, 'in selected range', '#7fe8ff');
        makeCard(cards, 'Average', avg, 'in selected range', '#7fe8ff');
        drawSingleSeries(points);
        renderHistoryTable(points);
      }} finally {{
        historyState.refreshing = false;
      }}
    }}

    async function initHistory(){{
      const latest = await (await fetch('/api/latest')).json();
      const names = (latest.items || []).map(x => x.cdn_name);
      const select = document.getElementById('cdnSelect');
      select.replaceChildren(...names.map(name => {{ const opt=document.createElement('option'); opt.value=name; opt.textContent=name; return opt; }}));
      historyState.cdn = names[0] || '';
      select.value = historyState.cdn;
      select.onchange = () => {{ historyState.cdn = select.value; loadHistory(); }};
      const rangeSelect = document.getElementById('rangeSelect');
      rangeSelect.onchange = () => {{ historyState.range = rangeSelect.value; loadHistory(); }};
      historyState.range = rangeSelect.value;
      await loadHistory();
      setInterval(loadHistory, 10000);
    }}

    initHistory();
    </script></body></html>"""

@app.post('/api/ingest')
def ingest(metric: MetricIn, x_agent_token: Optional[str] = Header(None)):
    if x_agent_token != TOKEN:
        raise HTTPException(status_code=401, detail='invalid token')
    if metric.target_port != 443:
        raise HTTPException(status_code=400, detail='target_port must be 443')
    ts = metric.ts or int(time.time())
    conn.execute(
        'INSERT INTO metrics(ts, cdn_name, host, target_port, connection_count) VALUES (?, ?, ?, ?, ?)',
        (ts, metric.cdn_name, metric.host, metric.target_port, metric.connection_count)
    )
    conn.commit()
    return {'status': 'ok', 'ts': ts}

@app.post('/api/metrics')
def legacy_metrics(metric: LegacyMetricIn, x_api_key: Optional[str] = Header(None), x_agent_token: Optional[str] = Header(None)):
    if x_api_key not in (TOKEN, LEGACY_API_KEY) and x_agent_token not in (TOKEN,):
        raise HTTPException(status_code=401, detail='invalid api key')
    ts = int(datetime.fromisoformat(metric.timestamp.replace('Z', '+00:00')).timestamp()) if metric.timestamp else int(time.time())
    conn.execute(
        'INSERT INTO metrics(ts, cdn_name, host, target_port, connection_count) VALUES (?, ?, ?, ?, ?)',
        (ts, metric.server_id, metric.server_ip or '', 443, metric.connection_count)
    )
    conn.commit()
    return {'status': 'ok', 'ts': ts, 'cdn_name': metric.server_id}

class DomainHitIn(BaseModel):
    cdn_name: str
    domain: str
    status_code: int
    hit_count: int = 1
    request_path: Optional[str] = None
    referer: Optional[str] = None
    user_agent: Optional[str] = None
    ts: Optional[int] = None

@app.post('/api/domain-hits')
def submit_domain_hits(hits: list[DomainHitIn], x_api_key: Optional[str] = Header(None)):
    if x_api_key not in (TOKEN, LEGACY_API_KEY):
        raise HTTPException(status_code=401, detail='invalid api key')
    now = int(time.time())
    for hit in hits:
        ts = hit.ts or now
        conn.execute(
            'INSERT INTO domain_hits(ts, cdn_name, domain, status_code, hit_count, request_path, referer, user_agent) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (ts, hit.cdn_name, hit.domain, hit.status_code, hit.hit_count, hit.request_path or '', hit.referer or '', hit.user_agent or '')
        )
    conn.commit()
    cleanup_old_domain_hits()
    return {'status': 'ok', 'count': len(hits)}

@app.get('/api/domain-hits')
def get_domain_hits(domain: str, from_ts: Optional[int] = None, to_ts: Optional[int] = None):
    hits = query_domain_hits(domain, from_ts, to_ts)
    return {'domain': domain, 'hits': hits}

@app.get('/api/domain-analytics')
def get_analytics(range: str = '24h', from_ts: Optional[int] = None, to_ts: Optional[int] = None):
    if not from_ts or not to_ts:
        spec = range_spec(range)
        from_ts = spec['since']
        to_ts = int(time.time())
    analytics = get_domain_analytics(from_ts, to_ts)
    return {'range': range, 'analytics': analytics, 'from': from_ts, 'to': to_ts}

@app.get('/api/latest')
def latest():
    return {'items': merge_latest_with_config()}

@app.get('/api/history')
def history(cdn_name: str, range: str = '24h'):
    spec, points = query_history(cdn_name, range)
    return {'cdn_name': cdn_name, 'range': range, 'label': spec['label'], 'stepLabel': spec['stepLabel'], 'points': points}

@app.get('/api/series')
def series(range: str = '24h'):
    spec, series_data = query_all_series(range)
    for cdn_name in get_configured_cdns():
        series_data.setdefault(cdn_name, [])
    return {'range': range, 'label': spec['label'], 'stepLabel': spec['stepLabel'], 'series': series_data}

@app.get('/api/domain-stats')
def domain_stats():
    return {'domains': get_domain_stats()}

@app.get('/api/map-config')
def map_config():
    latest_rows = get_latest_rows_by_cdn()
    markers = []
    for item in load_map_locations():
        latest = latest_rows.get(item['cdn_name'], {})
        markers.append({**item, **latest})
    return {'items': markers}

@app.get('/api/map-config/raw')
def map_config_raw():
    return {'items': [{'cdn_name': k, **(v if isinstance(v, dict) else {'place_name': v})} for k, v in load_map_config_raw().items()]}

@app.post('/api/map-config')
def upsert_map_config(item: MapConfigIn, token: Optional[str] = Cookie(None)):
    username = username_from_token(token)
    if not username:
        raise HTTPException(status_code=401, detail='Not authenticated')
    raw = load_map_config_raw()
    entry: dict = {}
    if item.place_name:
        entry['place_name'] = item.place_name
    if item.area_name:
        entry['area_name'] = item.area_name
    if item.lat is not None and item.lon is not None:
        entry['lat'] = item.lat
        entry['lon'] = item.lon
    if item.ip:
        entry['ip'] = item.ip

    if not entry:
        entry = ''
    elif isinstance(entry, dict) and set(entry.keys()) == {'place_name'}:
        entry = entry['place_name']
    raw[item.cdn_name] = entry
    save_map_config_raw(raw)
    logger.info('Map config upserted by %s for %s', username, item.cdn_name)
    return {'status': 'ok', 'cdn_name': item.cdn_name}

@app.delete('/api/map-config/{cdn_name}')
def delete_map_config(cdn_name: str, token: Optional[str] = Cookie(None)):
    username = username_from_token(token)
    if not username:
        raise HTTPException(status_code=401, detail='Not authenticated')
    raw = load_map_config_raw()
    if cdn_name in raw:
        del raw[cdn_name]
        save_map_config_raw(raw)
    logger.info('Map config deleted by %s for %s', username, cdn_name)
    return {'status': 'ok', 'cdn_name': cdn_name}
