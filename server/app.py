from fastapi import FastAPI, Header, HTTPException, Cookie, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional
import os, sqlite3, time, html, logging, json
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
conn.commit()

TOKEN = os.getenv('INGEST_TOKEN', 'change-me')
JWT_SECRET = os.getenv('JWT_SECRET', 'change-me-in-production')
JWT_ALGORITHM = 'HS256'
SESSION_HOURS = int(os.getenv('SESSION_HOURS', '24'))
RETENTION_DAYS = int(os.getenv('RETENTION_DAYS', '30'))
BOOTSTRAP_ADMIN_USERNAME = os.getenv('BOOTSTRAP_ADMIN_USERNAME', 'admin')
BOOTSTRAP_ADMIN_PASSWORD = os.getenv('BOOTSTRAP_ADMIN_PASSWORD', 'cdn-monitor-2026!')
AUTO_BOOTSTRAP_ADMIN = os.getenv('AUTO_BOOTSTRAP_ADMIN', 'true').lower() in ('1', 'true', 'yes', 'on')
MAP_CONFIG_FILE = os.getenv('MAP_CONFIG_FILE', '/app/data/cdn_map.json')

BANGLADESH_PLACES = {
    'dhaka': {'label': 'Dhaka', 'lat': 23.8103, 'lon': 90.4125},
    'chattogram': {'label': 'Chattogram', 'lat': 22.3569, 'lon': 91.7832},
    'chittagong': {'label': 'Chattogram', 'lat': 22.3569, 'lon': 91.7832},
    'khulna': {'label': 'Khulna', 'lat': 22.8456, 'lon': 89.5403},
    'rajshahi': {'label': 'Rajshahi', 'lat': 24.3745, 'lon': 88.6042},
    'sylhet': {'label': 'Sylhet', 'lat': 24.8949, 'lon': 91.8687},
    'barishal': {'label': 'Barishal', 'lat': 22.7010, 'lon': 90.3535},
    'barisal': {'label': 'Barishal', 'lat': 22.7010, 'lon': 90.3535},
    'rangpur': {'label': 'Rangpur', 'lat': 25.7439, 'lon': 89.2752},
    'mymensingh': {'label': 'Mymensingh', 'lat': 24.7471, 'lon': 90.4203},
    'coxsbazar': {'label': 'Cox’s Bazar', 'lat': 21.4272, 'lon': 92.0058},
    'cox\'s bazar': {'label': 'Cox’s Bazar', 'lat': 21.4272, 'lon': 92.0058},
    'cumilla': {'label': 'Cumilla', 'lat': 23.4607, 'lon': 91.1809},
    'comilla': {'label': 'Cumilla', 'lat': 23.4607, 'lon': 91.1809},
    'bogura': {'label': 'Bogura', 'lat': 24.8465, 'lon': 89.3773},
    'jashore': {'label': 'Jashore', 'lat': 23.1664, 'lon': 89.2080},
    'jessore': {'label': 'Jashore', 'lat': 23.1664, 'lon': 89.2080},
    'narayanganj': {'label': 'Narayanganj', 'lat': 23.6238, 'lon': 90.5000},
    'gazipur': {'label': 'Gazipur', 'lat': 23.9946, 'lon': 90.4203},
    'feni': {'label': 'Feni', 'lat': 23.0236, 'lon': 91.3849},
    'noakhali': {'label': 'Noakhali', 'lat': 22.8696, 'lon': 91.0995},
    'pabna': {'label': 'Pabna', 'lat': 24.0065, 'lon': 89.2372},
    'dinajpur': {'label': 'Dinajpur', 'lat': 25.6269, 'lon': 88.6378},
}

pwd_context = CryptContext(schemes=['argon2'], deprecated='auto')
app = FastAPI(title='CDN Monitoring System')

class MetricIn(BaseModel):
    cdn_name: str
    host: str
    target_port: int
    connection_count: int
    ts: Optional[int] = None

class MapConfigIn(BaseModel):
    cdn_name: str
    place_name: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

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
        return {'since': now - 86400, 'bucket': 3600, 'label': 'last 24 hours', 'stepLabel': 'hour'}
    if normalized in ('7d', 'week', 'weekly'):
        return {'since': now - 7 * 86400, 'bucket': 86400, 'label': 'last 7 days', 'stepLabel': 'day'}
    if normalized in ('30d', 'month', 'monthly'):
        return {'since': now - 30 * 86400, 'bucket': 86400, 'label': 'last 30 days', 'stepLabel': 'day'}
    return {'since': now - 86400, 'bucket': 3600, 'label': 'last 24 hours', 'stepLabel': 'hour'}

def query_history(cdn_name: str, range_key: str):
    spec = range_spec(range_key)
    rows = conn.execute(
        'SELECT (ts / ?) * ? AS bucket_ts, ROUND(AVG(connection_count)) AS connection_count, COUNT(*) AS samples '
        'FROM metrics WHERE cdn_name=? AND ts>=? GROUP BY bucket_ts ORDER BY bucket_ts',
        (spec['bucket'], spec['bucket'], cdn_name, spec['since'])
    ).fetchall()
    return spec, [{'ts': r[0], 'connection_count': int(r[1] or 0), 'samples': r[2]} for r in rows]

def query_all_series(range_key: str):
    spec = range_spec(range_key)
    rows = conn.execute(
        'SELECT cdn_name, (ts / ?) * ? AS bucket_ts, ROUND(AVG(connection_count)) AS connection_count, COUNT(*) AS samples '
        'FROM metrics WHERE ts>=? GROUP BY cdn_name, bucket_ts ORDER BY cdn_name, bucket_ts',
        (spec['bucket'], spec['bucket'], spec['since'])
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
        if isinstance(spec, str):
            place_name = spec
        elif isinstance(spec, dict):
            place_name = spec.get('place_name') or spec.get('place') or spec.get('location')
            lat = spec.get('lat')
            lon = spec.get('lon')

        lookup = BANGLADESH_PLACES.get((place_name or '').strip().lower()) if place_name else None
        if lookup:
            lat = lookup['lat'] if lat is None else lat
            lon = lookup['lon'] if lon is None else lon
            place_name = lookup['label']

        resolved.append({
            'cdn_name': cdn_name,
            'place_name': place_name or '',
            'lat': lat,
            'lon': lon,
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

def get_latest_rows_by_cdn():
    rows = conn.execute("""
    SELECT ts, cdn_name, host, target_port, connection_count
    FROM metrics
    WHERE (cdn_name, ts) IN (
      SELECT cdn_name, MAX(ts) FROM metrics GROUP BY cdn_name
    )
    ORDER BY cdn_name
    """).fetchall()
    return {
        r[1]: {'ts': r[0], 'cdn_name': r[1], 'host': r[2], 'target_port': r[3], 'connection_count': r[4]}
        for r in rows
    }

def merge_latest_with_config(default_count=0):
    latest_rows = get_latest_rows_by_cdn()
    configured = load_map_locations()
    items = []
    seen = set()
    for item in configured:
        row = latest_rows.get(item['cdn_name'])
        merged = {**item}
        if row:
            merged.update(row)
        else:
            merged.update({'ts': None, 'host': '', 'target_port': None, 'connection_count': default_count})
        items.append(merged)
        seen.add(item['cdn_name'])
    for cdn_name, row in latest_rows.items():
        if cdn_name not in seen:
            items.append({
                'cdn_name': cdn_name,
                'place_name': '',
                'lat': None,
                'lon': None,
                'resolved': False,
                **row,
            })
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

@app.post('/api/login')
def api_login(username: str = Form(...), password: str = Form(...)):
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
    .chart{{width:100%;height:320px;display:block;background:#081018;border:1px solid #1f3b4d;border-radius:10px}}
    table{{border-collapse:collapse;width:100%}}
    td,th{{border:1px solid #1f3b4d;padding:8px;text-align:left}}
    .empty{{padding:16px 0;opacity:.75}}
    </style>
    </head><body><div class='wrap'>
    <div class='nav'>
      <div>
        <h1 style='margin:0'>CDN Monitoring System</h1>
        <div class='muted' style='margin-top:6px'>Interactive overview, map, and history</div>
      </div>
      <div class='navlinks'>
        <a class='badge' href='/'>Home</a>
        <a class='badge' href='/map'>Bangladesh map</a>
        <a class='badge' href='/history'>History</a>
        <a class='badge' href='/management'>Management</a>
        <a class='badge' href='/logout'>Logout ({html.escape(username)})</a>
      </div>
    </div>

    <div class='cards' id='cards'></div>

    <div class='panel'>
      <h2>All CDN graph</h2>
      <div class='muted'>Default view: last 24 hours, all CDNs together</div>
      <svg id='homeChart' class='chart' viewBox='0 0 1200 320' preserveAspectRatio='none'></svg>
      <div id='legend' class='legend'></div>
    </div>

    <div class='panel'>
      <h2>Latest rows</h2>
      <div id='latestTable'></div>
    </div>

    </div><script>
    const state = {{ hidden: {{}} }};
    const palette = ['#7fe8ff','#ff8f70','#a4ff70','#d370ff','#ffd670','#70ffd8','#ffa8d8','#9cb2ff'];

    function esc(text){{ const div=document.createElement('div'); div.textContent=String(text ?? ''); return div.textContent; }}

    function setCard(container, title, value, sub=''){{
      const card=document.createElement('div'); card.className='card';
      card.innerHTML = '<div class="label">'+esc(title)+'</div><div class="value">'+esc(value)+'</div>' + (sub ? '<div class="muted" style="margin-top:6px">'+esc(sub)+'</div>' : '');
      container.appendChild(card);
    }}

    function renderCards(items){{
      const cards=document.getElementById('cards');
      cards.replaceChildren();
      const total = items.reduce((sum, item) => sum + Number(item.connection_count || 0), 0);
      setCard(cards, 'Total CDNs', items.length, 'current active sources');
      setCard(cards, 'Total connections', total, 'live latest counts');
      if(items.length){{
        const hottest = [...items].sort((a,b)=>Number(b.connection_count||0)-Number(a.connection_count||0))[0];
        setCard(cards, 'Highest count', hottest.connection_count, hottest.cdn_name + ' · ' + (hottest.host || 'waiting for data'));
      }}
      items.forEach(item => setCard(cards, item.cdn_name, item.connection_count, item.ts ? ((item.host || 'live') + ' : ' + String(item.target_port ?? '--')) : 'waiting for agent'));
    }}

    function renderLatestTable(items){{
      const target=document.getElementById('latestTable');
      if(!items.length){{ target.innerHTML = '<div class="empty">No data yet.</div>'; return; }}
      const table=document.createElement('table');
      const head=document.createElement('tr');
      ['CDN','Host','Port','Connections','Timestamp'].forEach(title => {{ const th=document.createElement('th'); th.textContent=title; head.appendChild(th); }});
      table.appendChild(head);
      items.forEach(item => {{
        const tr=document.createElement('tr');
        const tsText = item.ts ? new Date(item.ts*1000).toLocaleString() : 'waiting for agent';
        [item.cdn_name, item.host || 'waiting for agent', String(item.target_port ?? '--'), String(item.connection_count ?? 0), tsText].forEach(value => {{ const td=document.createElement('td'); td.textContent=value; tr.appendChild(td); }});
        table.appendChild(tr);
      }});
      target.replaceChildren(table);
    }}

    function renderLegend(series){{
      const legend=document.getElementById('legend');
      legend.replaceChildren();
      const names=Object.keys(series).sort();
      names.forEach((name, idx) => {{
        const btn=document.createElement('button');
        btn.textContent=name;
        btn.style.borderColor=palette[idx % palette.length];
        if(state.hidden[name]) btn.classList.add('off');
        btn.onclick = () => {{ state.hidden[name] = !state.hidden[name]; loadGraphs(); }};
        legend.appendChild(btn);
      }});
    }}

    function renderHomeChart(series){{
      const svg=document.getElementById('homeChart');
      svg.replaceChildren();
      const activeNames = Object.keys(series).filter(name => !state.hidden[name] && series[name] && series[name].length);
      const allTimes = [...new Set(activeNames.flatMap(name => series[name].map(p => p.ts)))].sort((a,b)=>a-b);
      const w=1200, h=320, padL=50, padR=18, padT=18, padB=34;
      if(!allTimes.length){{
        const empty=document.createElementNS('http://www.w3.org/2000/svg','text');
        empty.setAttribute('x','20'); empty.setAttribute('y','30'); empty.setAttribute('fill','#d8f7ff'); empty.textContent='No graph data yet.';
        svg.appendChild(empty); return;
      }}
      const xAt = ts => padL + (allTimes.length === 1 ? 0 : ((allTimes.indexOf(ts) / (allTimes.length - 1)) * (w - padL - padR)));
      const maxValue = Math.max(1, ...activeNames.flatMap(name => series[name].map(p => Number(p.connection_count || 0))));
      const yAt = value => h - padB - ((Number(value || 0) / maxValue) * (h - padT - padB));
      for(let i=0;i<5;i++){{
        const y = padT + i * ((h - padT - padB)/4);
        const line=document.createElementNS('http://www.w3.org/2000/svg','line');
        line.setAttribute('x1', padL); line.setAttribute('x2', w-padR); line.setAttribute('y1', y); line.setAttribute('y2', y);
        line.setAttribute('stroke', '#1f3b4d'); line.setAttribute('stroke-width', '1');
        svg.appendChild(line);
      }}
      activeNames.forEach((name, idx) => {{
        const points = series[name] || [];
        const lookup = new Map(points.map(p => [p.ts, p.connection_count]));
        let pathD = '';
        allTimes.forEach(ts => {{
          if(!lookup.has(ts)) return;
          const x = xAt(ts).toFixed(1);
          const y = yAt(lookup.get(ts)).toFixed(1);
          pathD += (pathD ? ' L ' : 'M ') + x + ' ' + y;
        }});
        if(!pathD) return;
        const path=document.createElementNS('http://www.w3.org/2000/svg','path');
        path.setAttribute('d', pathD);
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', palette[idx % palette.length]);
        path.setAttribute('stroke-width', '3');
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(path);
        points.forEach(point => {{
          const circle=document.createElementNS('http://www.w3.org/2000/svg','circle');
          circle.setAttribute('cx', xAt(point.ts));
          circle.setAttribute('cy', yAt(point.connection_count));
          circle.setAttribute('r', '4');
          circle.setAttribute('fill', palette[idx % palette.length]);
          const title=document.createElementNS('http://www.w3.org/2000/svg','title');
          title.textContent = name + ' · ' + point.connection_count + ' @ ' + new Date(point.ts*1000).toLocaleString();
          circle.appendChild(title);
          svg.appendChild(circle);
        }});
      }});
      const axis=document.createElementNS('http://www.w3.org/2000/svg','line');
      axis.setAttribute('x1', padL); axis.setAttribute('x2', w-padR); axis.setAttribute('y1', h-padB); axis.setAttribute('y2', h-padB);
      axis.setAttribute('stroke', '#7fe8ff'); axis.setAttribute('stroke-width', '1');
      svg.appendChild(axis);
      const maxLabel=document.createElementNS('http://www.w3.org/2000/svg','text');
      maxLabel.setAttribute('x', '12'); maxLabel.setAttribute('y', '22'); maxLabel.setAttribute('fill', '#d8f7ff'); maxLabel.setAttribute('font-size', '12');
      maxLabel.textContent = 'max ' + maxValue;
      svg.appendChild(maxLabel);
    }}

    async function loadGraphs(){{
      const [latestRes, seriesRes] = await Promise.all([fetch('/api/latest'), fetch('/api/series?range=24h')]);
      const latest = await latestRes.json();
      const series = await seriesRes.json();
      renderCards(latest.items || []);
      renderLegend(series.series || {{}});
      renderHomeChart(series.series || {{}});
      renderLatestTable(latest.items || []);
    }}

    loadGraphs(); setInterval(loadGraphs, 5000);
    </script></body></html>"""

@app.get('/map', response_class=HTMLResponse)
def map_page(token: Optional[str] = Cookie(None)):
    username = username_from_token(token)
    if not username:
        return RedirectResponse(url='/login', status_code=303)
    return f"""<!doctype html><html><head><title>CDN Monitor Map</title>
    <meta name='viewport' content='width=device-width, initial-scale=1'>
    <link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css' integrity='sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=' crossorigin=''/>
    <style>
    body{{font-family:Arial;background:#081018;color:#d8f7ff;padding:20px;margin:0}}
    .wrap{{max-width:1400px;margin:0 auto}}
    .nav{{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:18px}}
    .navlinks{{display:flex;gap:14px;flex-wrap:wrap}}
    .badge{{display:inline-block;padding:4px 10px;border:1px solid #1f3b4d;border-radius:999px;background:#0a1520;color:#7fe8ff;text-decoration:none}}
    .grid{{display:grid;grid-template-columns:1.5fr .9fr;gap:14px}}
    #map{{height:760px;border:1px solid #1f3b4d;border-radius:12px;overflow:hidden;background:#050b12}}
    .panel{{background:#0a1520;border:1px solid #1f3b4d;border-radius:12px;padding:16px}}
    .item{{border-bottom:1px solid #1f3b4d;padding:10px 0}}
    .item:last-child{{border-bottom:none}}
    .muted{{opacity:.75}}
    .row{{display:flex;align-items:center;gap:8px}}
    .pulse-marker{{width:16px;height:16px;border-radius:999px;background:#27d36b;box-shadow:0 0 0 0 rgba(39,211,107,.65);animation:pulse 1.4s infinite;position:relative}}
    .pulse-marker::after{{content:'';position:absolute;inset:4px;border-radius:999px;background:#b9ffd2;opacity:.95}}
    @keyframes pulse{{0%{{box-shadow:0 0 0 0 rgba(39,211,107,.55)}}70%{{box-shadow:0 0 0 14px rgba(39,211,107,0)}}100%{{box-shadow:0 0 0 0 rgba(39,211,107,0)}}}}
    </style>
    </head><body><div class='wrap'>
    <div class='nav'>
      <div>
        <h1 style='margin:0'>Bangladesh CDN Map</h1>
        <div class='muted' style='margin-top:6px'>Configure map points in <code>/app/data/cdn_map.json</code></div>
      </div>
      <div class='navlinks'>
        <a class='badge' href='/'>Home</a>
        <a class='badge' href='/map'>Bangladesh map</a>
        <a class='badge' href='/history'>History</a>
        <a class='badge' href='/management'>Management</a>
        <a class='badge' href='/logout'>Logout ({html.escape(username)})</a>
      </div>
    </div>
    <div class='grid'>
      <div id='map'></div>
      <div class='panel'>
        <h2 style='margin-top:0'>Configured CDNs</h2>
        <div id='markerList'></div>
      </div>
    </div>
    </div>
    <script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js' integrity='sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=' crossorigin=''></script>
    <script>
    async function initMap(){{
      const r = await fetch('/api/map-config');
      const d = await r.json();
      const map = L.map('map', {{ zoomControl: true }}).setView([23.6850, 90.3563], 7);
      L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        maxZoom: 18,
        subdomains: 'abcd',
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
      }}).addTo(map);
      const bounds = [[20.5, 88.0], [26.8, 92.8]];
      map.fitBounds(bounds);
      const list = document.getElementById('markerList');
      list.replaceChildren();
      const markers = (d.items || []).filter(x => x.resolved);
      if(!markers.length){{
        list.innerHTML = '<div class="muted">No map config yet. Add entries in /app/data/cdn_map.json.</div>';
        return;
      }}
      markers.forEach((item, idx) => {{
        const icon = L.divIcon({{ className: '', html: '<div class="pulse-marker"></div>', iconSize: [16,16], iconAnchor: [8,8] }});
        const marker = L.marker([item.lat, item.lon], {{ icon }}).addTo(map);
        marker.bindPopup(`<b>${{item.cdn_name}}</b><br>${{item.place_name}}<br>Count: ${{item.connection_count ?? 'n/a'}}`);
        const row = document.createElement('div');
        row.className = 'item';
        row.innerHTML = '<div class="row"><span class="pulse-marker" style="display:inline-block;transform:scale(.65)"></span><b>' + item.cdn_name + '</b></div><div class="muted">' + item.place_name + '</div><div class="muted">count: ' + (item.connection_count ?? 'n/a') + '</div>';
        list.appendChild(row);
      }});
      const unresolved = (d.items || []).filter(x => !x.resolved);
      unresolved.forEach(item => {{
        const row = document.createElement('div');
        row.className = 'item';
        row.innerHTML = '<b>' + item.cdn_name + '</b><br><span class="muted">Unresolved place: ' + (item.place_name || 'missing') + '</span>';
        list.appendChild(row);
      }});
    }}
    initMap();
    </script></body></html>"""

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
        <a class='badge' href='/map'>Bangladesh map</a>
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
          <label>Place name</label><input id='placeName' placeholder='Dhaka'>
          <label>Latitude (optional)</label><input id='lat' type='number' step='any' placeholder='23.8103'>
          <label>Longitude (optional)</label><input id='lon' type='number' step='any' placeholder='90.4125'>
          <div class='section' style='display:flex;gap:10px;flex-wrap:wrap'>
            <button type='submit'>Save CDN</button>
            <button type='button' id='seedBtn' class='secondary'>Seed example CDNs</button>
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
      ['Status','CDN','Place','Lat/Lon','Live count','Actions'].forEach(title => { const th=document.createElement('th'); th.textContent=title; head.appendChild(th); });
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
        const placeTd = document.createElement('td'); placeTd.textContent = item.place_name || ''; row.appendChild(placeTd);
        const latLonTd = document.createElement('td'); latLonTd.textContent = (item.lat != null && item.lon != null) ? item.lat + ', ' + item.lon : 'unresolved'; row.appendChild(latLonTd);
        const liveTd = document.createElement('td'); liveTd.textContent = live ? String(live.connection_count) : '0'; row.appendChild(liveTd);

        const actionsTd = document.createElement('td');
        actionsTd.className = 'actions';
        const del = document.createElement('button');
        del.type = 'button';
        del.textContent = 'Delete';
        del.onclick = async () => {
          if(!confirm('Remove ' + item.cdn_name + '?')) return;
          await fetch('/api/map-config/' + encodeURIComponent(item.cdn_name), { method: 'DELETE' });
          refreshConfig();
        };
        actionsTd.appendChild(del);
        row.appendChild(actionsTd);
        table.appendChild(row);
      });
      list.appendChild(table);
    }

    document.getElementById('cdnForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const payload = {
        cdn_name: document.getElementById('cdnName').value.trim(),
        place_name: document.getElementById('placeName').value.trim() || null,
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

    document.getElementById('seedBtn').addEventListener('click', async () => {
      const seeds = [
        {cdn_name:'cdn1', place_name:'Dhaka'},
        {cdn_name:'cdn2', place_name:'Chattogram'},
        {cdn_name:'cdn3', place_name:'Khulna'},
      ];
      for (const item of seeds) {
        await fetch('/api/map-config', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(item) });
      }
      refreshConfig();
    });

    refreshConfig();
    </script></body></html>""".replace('__USERNAME__', html.escape(username))

@app.get('/history', response_class=HTMLResponse)
def history_page(token: Optional[str] = Cookie(None)):
    username = username_from_token(token)
    if not username:
        return RedirectResponse(url='/login', status_code=303)
    return """<!doctype html><html><head><title>CDN Monitor History</title>
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
    .chart{{width:100%;height:340px;display:block;background:#081018;border:1px solid #1f3b4d;border-radius:10px}}
    .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}}
    .card{{background:#0a1520;border:1px solid #1f3b4d;border-radius:12px;padding:14px}}
    .card .label{{font-size:12px;opacity:.75;margin-bottom:6px}}
    .card .value{{font-size:24px;font-weight:700}}
    table{{border-collapse:collapse;width:100%}}
    td,th{{border:1px solid #1f3b4d;padding:8px;text-align:left}}
    .muted{{opacity:.75}}
    .empty{{padding:16px 0;opacity:.75}}
    </style>
    </head><body><div class='wrap'>
    <div class='nav'>
      <div>
        <h1 style='margin:0'>Historical data</h1>
        <div class='muted' style='margin-top:6px'>Default is 24 hours, switch to weekly or monthly anytime.</div>
      </div>
      <div class='navlinks'>
        <a class='badge' href='/'>Home</a>
        <a class='badge' href='/map'>Bangladesh map</a>
        <a class='badge' href='/history'>History</a>
        <a class='badge' href='/management'>Management</a>
        <a class='badge' href='/logout'>Logout (__USERNAME__)</a>
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
      </div>
      <div class='cards' id='historyCards'></div>
      <svg id='historyChart' class='chart' viewBox='0 0 1200 340' preserveAspectRatio='none'></svg>
      <div id='historyEmpty' class='empty' style='display:none'>No historical data for this selection yet.</div>
    </div>

    <div class='panel'>
      <h2 style='margin-top:0'>Points</h2>
      <div id='historyTable'></div>
    </div>
    </div>
    <script>
    const historyState = {{ cdn: null, range: '24h' }};
    const colors = ['#7fe8ff'];

    function makeCard(parent, label, value, sub=''){{
      const card=document.createElement('div'); card.className='card';
      card.innerHTML = '<div class="label">'+label+'</div><div class="value">'+value+'</div>' + (sub ? '<div class="muted" style="margin-top:6px">'+sub+'</div>' : '');
      parent.appendChild(card);
    }}

    function drawSingleSeries(points){{
      const svg=document.getElementById('historyChart');
      const empty=document.getElementById('historyEmpty');
      svg.replaceChildren();
      if(!points.length){{ empty.style.display='block'; return; }}
      empty.style.display='none';
      const w=1200, h=340, padL=50, padR=18, padT=18, padB=38;
      const maxValue=Math.max(1, ...points.map(p => Number(p.connection_count || 0)));
      const minTs=points[0].ts, maxTs=points[points.length-1].ts;
      const xAt = ts => padL + ((ts - minTs) / Math.max(1, (maxTs - minTs))) * (w - padL - padR);
      const yAt = value => h - padB - ((Number(value || 0) / maxValue) * (h - padT - padB));
      for(let i=0;i<5;i++){{
        const y = padT + i * ((h - padT - padB)/4);
        const line=document.createElementNS('http://www.w3.org/2000/svg','line');
        line.setAttribute('x1', padL); line.setAttribute('x2', w-padR); line.setAttribute('y1', y); line.setAttribute('y2', y);
        line.setAttribute('stroke', '#1f3b4d'); line.setAttribute('stroke-width', '1');
        svg.appendChild(line);
      }}
      let d='';
      points.forEach((p, idx) => {{
        const x=xAt(p.ts).toFixed(1), y=yAt(p.connection_count).toFixed(1);
        d += (idx ? ' L ' : 'M ') + x + ' ' + y;
      }});
      const path=document.createElementNS('http://www.w3.org/2000/svg','path');
      path.setAttribute('d', d);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', '#7fe8ff');
      path.setAttribute('stroke-width', '3');
      svg.appendChild(path);
      points.forEach(point => {{
        const circle=document.createElementNS('http://www.w3.org/2000/svg','circle');
        circle.setAttribute('cx', xAt(point.ts));
        circle.setAttribute('cy', yAt(point.connection_count));
        circle.setAttribute('r', '4');
        circle.setAttribute('fill', '#7fe8ff');
        const title=document.createElementNS('http://www.w3.org/2000/svg','title');
        title.textContent = point.connection_count + ' @ ' + new Date(point.ts*1000).toLocaleString();
        circle.appendChild(title);
        svg.appendChild(circle);
      }});
      const axis=document.createElementNS('http://www.w3.org/2000/svg','line');
      axis.setAttribute('x1', padL); axis.setAttribute('x2', w-padR); axis.setAttribute('y1', h-padB); axis.setAttribute('y2', h-padB);
      axis.setAttribute('stroke', '#7fe8ff'); axis.setAttribute('stroke-width', '1');
      svg.appendChild(axis);
    }}

    function renderHistoryTable(points){{
      const target=document.getElementById('historyTable');
      if(!points.length){{ target.innerHTML = '<div class="empty">No points yet.</div>'; return; }}
      const table=document.createElement('table');
      const head=document.createElement('tr');
      ['Timestamp','Connections'].forEach(title => {{ const th=document.createElement('th'); th.textContent=title; head.appendChild(th); }});
      table.appendChild(head);
      points.forEach(point => {{
        const tr=document.createElement('tr');
        [new Date(point.ts*1000).toLocaleString(), String(point.connection_count)].forEach(value => {{ const td=document.createElement('td'); td.textContent=value; tr.appendChild(td); }});
        table.appendChild(tr);
      }});
      target.replaceChildren(table);
    }}

    async function loadHistory(){{
      if(!historyState.cdn) return;
      const r=await fetch('/api/history?cdn_name=' + encodeURIComponent(historyState.cdn) + '&range=' + encodeURIComponent(historyState.range));
      const d=await r.json();
      document.getElementById('historyMeta').textContent = d.label + ' · ' + historyState.cdn;
      const points = d.points || [];
      const current = points.length ? points[points.length - 1].connection_count : 'n/a';
      const max = points.length ? Math.max(...points.map(p => p.connection_count)) : 0;
      const avg = points.length ? Math.round(points.reduce((sum,p)=>sum + Number(p.connection_count||0),0) / points.length) : 0;
      const cards=document.getElementById('historyCards');
      cards.replaceChildren();
      makeCard(cards, 'Current', current, 'latest point');
      makeCard(cards, 'Maximum', max, 'in selected range');
      makeCard(cards, 'Average', avg, 'in selected range');
      drawSingleSeries(points);
      renderHistoryTable(points);
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
      loadHistory();
    }}

    initHistory();
    </script></body></html>""".replace('__USERNAME__', html.escape(username))

@app.post('/api/ingest')
def ingest(metric: MetricIn, x_agent_token: Optional[str] = Header(None)):
    if x_agent_token != TOKEN:
        raise HTTPException(status_code=401, detail='invalid token')
    ts = metric.ts or int(time.time())
    conn.execute(
        'INSERT INTO metrics(ts, cdn_name, host, target_port, connection_count) VALUES (?, ?, ?, ?, ?)',
        (ts, metric.cdn_name, metric.host, metric.target_port, metric.connection_count)
    )
    conn.commit()
    return {'status': 'ok', 'ts': ts}

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
    for item in load_map_locations():
        series_data.setdefault(item['cdn_name'], [])
    return {'range': range, 'label': spec['label'], 'stepLabel': spec['stepLabel'], 'series': series_data}

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
    if item.lat is not None and item.lon is not None:
        raw[item.cdn_name] = {'place_name': item.place_name or '', 'lat': item.lat, 'lon': item.lon}
    else:
        raw[item.cdn_name] = item.place_name or ''
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
