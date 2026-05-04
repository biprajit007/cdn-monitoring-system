from fastapi import FastAPI, Header, HTTPException, Cookie, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional
import os, sqlite3, time, html, logging
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

pwd_context = CryptContext(schemes=['argon2'], deprecated='auto')
app = FastAPI(title='CDN Monitoring System')

class MetricIn(BaseModel):
    cdn_name: str
    host: str
    target_port: int
    connection_count: int
    ts: Optional[int] = None

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

def cleanup_old_metrics():
    cutoff = int(time.time()) - (RETENTION_DAYS * 86400)
    conn.execute('DELETE FROM metrics WHERE ts < ?', (cutoff,))
    conn.commit()
    logger.info(f'Cleaned up metrics older than {RETENTION_DAYS} days')

@app.get('/login', response_class=HTMLResponse)
def login_page():
    return """<!doctype html><html><head><title>CDN Monitor Login</title>
    <style>body{font-family:Arial;background:#081018;color:#d8f7ff;padding:20px;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
    .login-box{border:1px solid #1f3b4d;padding:30px;border-radius:5px;width:300px}input{width:100%;padding:10px;margin:10px 0;background:#0a1520;border:1px solid #1f3b4d;color:#d8f7ff;box-sizing:border-box}
    button{width:100%;padding:10px;margin-top:10px;background:#1f3b4d;color:#7fe8ff;border:1px solid #7fe8ff;cursor:pointer}button:hover{background:#2a4a5d}
    .error{color:#ff6b6b;margin-bottom:10px}</style>
    </head><body><div class='login-box'><h1>CDN Monitor</h1>
    <form method='post' action='/api/login'><input type='text' name='username' placeholder='Username' required>
    <input type='password' name='password' placeholder='Password' required><button type='submit'>Login</button></form></div></body></html>"""

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
def dashboard(username: str = Depends(verify_token)):
    cleanup_old_metrics()
    return f"""<!doctype html><html><head><title>CDN Monitor</title>
    <style>body{{font-family:Arial;background:#081018;color:#d8f7ff;padding:20px}}table{{border-collapse:collapse;width:100%}}
    td,th{{border:1px solid #1f3b4d;padding:8px}}a{{color:#7fe8ff}}.logout{{float:right}}</style>
    </head><body><h1>CDN Monitoring System</h1><a href='/logout' class='logout'>Logout ({html.escape(username)})</a>
    <p>Endpoints: <a href='/api/latest'>/api/latest</a></p><div id='app'></div><script>
    function cell(text){{const td=document.createElement('td'); td.textContent = text; return td;}}
    async function load(){{const r=await fetch('/api/latest');const d=await r.json();
    const table=document.createElement('table');
    const head=document.createElement('tr');
    for (const title of ['CDN','Host','Port','Connections','Timestamp']){{head.appendChild(cell(title));}}
    table.appendChild(head);
    for(const x of d.items){{
      const tr=document.createElement('tr');
      tr.appendChild(cell(x.cdn_name));
      tr.appendChild(cell(x.host));
      tr.appendChild(cell(String(x.target_port)));
      tr.appendChild(cell(String(x.connection_count)));
      tr.appendChild(cell(new Date(x.ts*1000).toLocaleString()));
      table.appendChild(tr);
    }}
    const app=document.getElementById('app'); app.replaceChildren(table);}}
    load(); setInterval(load,5000);
    </script></body></html>"""

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
    rows = conn.execute("""
    SELECT ts, cdn_name, host, target_port, connection_count
    FROM metrics
    WHERE (cdn_name, ts) IN (
      SELECT cdn_name, MAX(ts) FROM metrics GROUP BY cdn_name
    )
    ORDER BY cdn_name
    """).fetchall()
    return {'items': [
        {'ts': r[0], 'cdn_name': r[1], 'host': r[2], 'target_port': r[3], 'connection_count': r[4]}
        for r in rows
    ]}

@app.get('/api/history')
def history(cdn_name: str, minutes: int = 60):
    since = int(time.time()) - minutes * 60
    rows = conn.execute(
        'SELECT ts, connection_count FROM metrics WHERE cdn_name=? AND ts>=? ORDER BY ts',
        (cdn_name, since)
    ).fetchall()
    return {'cdn_name': cdn_name, 'points': [{'ts': r[0], 'connection_count': r[1]} for r in rows]}
