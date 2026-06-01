from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.routes.auth import router as auth_router
from app.routes.auth import author_router
from app.routes.orders import orders_router
from app.routes.products import products_router, public_products_router

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the original auth routes
app.include_router(auth_router)

# Include the new author routes
app.include_router(author_router)

# Include the products routes
app.include_router(products_router)
app.include_router(public_products_router)

# Include the order routes
app.include_router(orders_router)


HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>API — Backend</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700&display=swap" rel="stylesheet" />
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg: #0b0c0e;
    --surface: #141618;
    --border: rgba(255,255,255,0.07);
    --border-hover: rgba(255,255,255,0.14);
    --text: #f0ede8;
    --muted: #6b6a66;
    --accent: #e8c97a;
    --accent-dim: rgba(232,201,122,0.12);
    --green: #4ade80;
    --green-dim: rgba(74,222,128,0.1);
    --blue: #7dd3fc;
    --blue-dim: rgba(125,211,252,0.1);
    --mono: 'DM Mono', monospace;
    --display: 'Syne', sans-serif;
  }

  html, body { height: 100%; background: var(--bg); color: var(--text); font-family: var(--mono); }

  body {
    display: grid;
    place-items: start center;
    min-height: 100vh;
    padding: 3rem 1.5rem 4rem;
  }

  .wrap { width: 100%; max-width: 680px; }

  /* Header */
  .header { margin-bottom: 2.5rem; animation: fadeUp 0.5s ease both; }
  .dot-row { display: flex; align-items: center; gap: 8px; margin-bottom: 1rem; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); position: relative; }
  .dot::after {
    content: '';
    position: absolute; inset: -4px;
    border-radius: 50%;
    border: 1.5px solid var(--green);
    opacity: 0;
    animation: ping 2s ease infinite;
  }
  @keyframes ping {
    0%   { transform: scale(1); opacity: 0.6; }
    70%  { transform: scale(2.2); opacity: 0; }
    100% { opacity: 0; }
  }
  .status-text { font-size: 11px; color: var(--green); letter-spacing: 0.1em; text-transform: uppercase; }

  .api-name {
    font-family: var(--display);
    font-size: clamp(28px, 5vw, 40px);
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.02em;
    line-height: 1.1;
  }
  .api-name span { color: var(--accent); }
  .tagline { font-size: 12px; color: var(--muted); margin-top: 8px; letter-spacing: 0.04em; }

  /* Divider */
  .rule { border: none; border-top: 1px solid var(--border); margin: 2rem 0; }

  /* Stats row */
  .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 2rem; animation: fadeUp 0.5s 0.1s ease both; }
  .stat {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
  }
  .stat-label { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 6px; }
  .stat-val { font-size: 20px; font-weight: 500; color: var(--text); }
  .stat-val.ok { color: var(--green); }
  .stat-val.amber { color: var(--accent); }

  /* Section */
  .section-title { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 10px; }

  /* Routes */
  .routes { display: flex; flex-direction: column; gap: 6px; margin-bottom: 2rem; animation: fadeUp 0.5s 0.2s ease both; }
  .route {
    display: flex; align-items: center; gap: 10px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
    transition: border-color 0.15s;
  }
  .route:hover { border-color: var(--border-hover); }
  .badge {
    font-size: 9px; font-weight: 500;
    padding: 3px 7px;
    border-radius: 4px;
    min-width: 42px;
    text-align: center;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    flex-shrink: 0;
  }
  .get  { background: var(--blue-dim);  color: var(--blue); }
  .post { background: var(--green-dim); color: var(--green); }
  .route-path { font-size: 12px; color: var(--text); flex: 1; }
  .route-tag { font-size: 10px; color: var(--muted); }

  /* Docs */
  .docs { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; animation: fadeUp 0.5s 0.3s ease both; }
  .doc-link {
    display: flex; align-items: center; gap: 10px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
    text-decoration: none;
    color: var(--text);
    transition: border-color 0.15s, background 0.15s;
  }
  .doc-link:hover { border-color: var(--accent); background: var(--accent-dim); }
  .doc-icon { font-size: 18px; color: var(--accent); }
  .doc-info { flex: 1; }
  .doc-name { font-family: var(--display); font-size: 13px; font-weight: 600; }
  .doc-path { font-size: 10px; color: var(--muted); margin-top: 2px; }
  .arrow { font-size: 11px; color: var(--muted); }

  /* Footer */
  .footer { margin-top: 2.5rem; font-size: 10px; color: var(--muted); text-align: center; letter-spacing: 0.05em; animation: fadeUp 0.5s 0.4s ease both; }

  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
  }
</style>
</head>
<body>
<div class="wrap">

  <div class="header">
    <div class="dot-row">
      <div class="dot"></div>
      <span class="status-text">Running</span>
    </div>
    <h1 class="api-name">Backend <span>API</span></h1>
    <p class="tagline">FastAPI · Python · REST</p>
  </div>

  <div class="stats">
    <div class="stat">
      <div class="stat-label">Status</div>
      <div class="stat-val ok">200 OK</div>
    </div>
    <div class="stat">
      <div class="stat-label">Routers</div>
      <div class="stat-val amber">5</div>
    </div>
    <div class="stat">
      <div class="stat-label">CORS</div>
      <div class="stat-val ok">Open</div>
    </div>
  </div>

  <hr class="rule" />

  <p class="section-title">Endpoints</p>
  <div class="routes">
    <div class="route">
      <span class="badge get">GET</span>
      <span class="route-path">/</span>
      <span class="route-tag">root</span>
    </div>
    <div class="route">
      <span class="badge post">POST</span>
      <span class="route-path">/auth/…</span>
      <span class="route-tag">auth_router</span>
    </div>
    <div class="route">
      <span class="badge get">GET</span>
      <span class="route-path">/author/…</span>
      <span class="route-tag">author_router</span>
    </div>
    <div class="route">
      <span class="badge get">GET</span>
      <span class="route-path">/products/…</span>
      <span class="route-tag">products_router</span>
    </div>
    <div class="route">
      <span class="badge get">GET</span>
      <span class="route-path">/public/products/…</span>
      <span class="route-tag">public_products_router</span>
    </div>
  </div>

  <hr class="rule" />

  <p class="section-title">Documentation</p>
  <div class="docs">
    <a class="doc-link" href="/docs">
      <span class="doc-icon"></span>
      <div class="doc-info">
        <div class="doc-name">Swagger UI</div>
        <div class="doc-path">/docs</div>
      </div>
      <span class="arrow">↗</span>
    </a>
    <a class="doc-link" href="/redoc">
      <span class="doc-icon"></span>
      <div class="doc-info">
        <div class="doc-name">ReDoc</div>
        <div class="doc-path">/redoc</div>
      </div>
      <span class="arrow">↗</span>
    </a>
  </div>

  <div class="footer">Built with FastAPI · All systems operational</div>

</div>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def root():
    return HTML