#!/usr/bin/env bash
# install.sh — git pull -> deploy -> DB setup + migrate -> pm2 -> health check
#
#   bash install.sh
#
# Env overrides:
#   BRANCH PORT FRONTEND_PORT HOST PUBLIC_HOST WORKERS APP_NAME HEALTH_TIMEOUT
#   DB_HOST DB_PORT DB_NAME DB_USER DB_PASS   MySQL/MariaDB settings, applied when backend/.env is first created
#   USE_SQLITE=1                              keep the .env.example SQLite default instead of switching to MySQL
set -Eeuo pipefail

APP_NAME="${APP_NAME:-jdk_erp}"
FRONTEND_APP_NAME="${FRONTEND_APP_NAME:-${APP_NAME}-frontend}"
REPO_URL="${REPO_URL:-https://github.com/BT-Rajan/jdk_erp.git}"
BRANCH="${BRANCH:-main}"
HOST="${HOST:-0.0.0.0}"
# What the *browser* uses to reach this box -- HOST is a bind address
# (0.0.0.0 isn't a valid URL host), so CORS_ORIGINS and VITE_API_URL are
# derived from this instead. Override for a real domain/IP deployment.
PUBLIC_HOST="${PUBLIC_HOST:-localhost}"
PORT="${PORT:-8989}"
FRONTEND_PORT="${FRONTEND_PORT:-7173}"
WORKERS="${WORKERS:-1}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-60}"
USE_SQLITE="${USE_SQLITE:-0}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_NAME="${DB_NAME:-jdk_erp}"
DB_USER="${DB_USER:-app_user}"
DB_PASS="${DB_PASS:-Chennai#44}"
export USE_SQLITE DB_HOST DB_PORT DB_NAME DB_USER DB_PASS

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  ✘ %s\033[0m\n' "$*" >&2; exit 1; }
trap 'die "Failed at line $LINENO: $BASH_COMMAND"' ERR
need() { command -v "$1" >/dev/null 2>&1 || die "Missing required tool: $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -z "${APP_DIR:-}" ]; then
  if git -C "$SCRIPT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    APP_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
  else
    APP_DIR="$SCRIPT_DIR/jdk_erp"
  fi
fi

# ───────────────────────── 1. prerequisites ─────────────────────────
step "1/8 Prerequisites"
need git; need curl; need node; need npm
PYBIN="$(command -v python3 || command -v python)" || die "Python 3.11+ not found"
"$PYBIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Python 3.11+ required (found $("$PYBIN" -V 2>&1))"
if ! command -v pm2 >/dev/null 2>&1; then warn "pm2 not found — installing globally"; npm install -g pm2; fi
ok "git, node $(node -v), $("$PYBIN" -V 2>&1), pm2 $(pm2 -v)"

# ───────────────────────── 2. git pull ─────────────────────────
step "2/8 Git pull ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
  cd "$APP_DIR"
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    warn "Local tracked changes found — stashing (recover with: git stash list)"
    git stash push -m "install.sh $(date +%Y%m%d-%H%M%S)" >/dev/null
  fi
  git fetch --all --prune
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
else
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  cd "$APP_DIR"
fi
ok "At $(git rev-parse --short HEAD) — $(git log -1 --pretty=%s)"
BACKEND="$APP_DIR/backend"
[ -f "$BACKEND/requirements.txt" ] || die "backend/requirements.txt not found in $APP_DIR"

# ───────────────────────── 3. install dependencies ─────────────────────────
step "3/8 Install dependencies"
cd "$BACKEND"
[ -d .venv ] || "$PYBIN" -m venv .venv
VPY=""
for p in "$BACKEND/.venv/bin/python" "$BACKEND/.venv/Scripts/python.exe"; do
  if [ -x "$p" ]; then VPY="$p"; break; fi
done
[ -n "$VPY" ] || die "venv python not found in $BACKEND/.venv"
"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet -r requirements.txt
ok "Python dependencies installed"

FRONTEND="$APP_DIR/frontend"
HAS_FRONTEND=0
FRONTEND_MODE=""  # "preview" (built, served via vite preview) or "dev"
if [ -f "$FRONTEND/package.json" ]; then
  HAS_FRONTEND=1
  script_exists() { node -e 'process.exit(((require("./package.json").scripts)||{})[process.argv[1]]?0:1)' "$1"; }
  ( cd "$FRONTEND"
    if [ -f package-lock.json ]; then npm ci || npm install; else npm install; fi )
  if ( cd "$FRONTEND" && script_exists build ); then FRONTEND_MODE="preview"; else FRONTEND_MODE="dev"; fi
  ok "Frontend dependencies installed ($([ "$FRONTEND_MODE" = preview ] && echo "will build" || echo "no build script — will run dev server"))"
else
  warn "frontend/ has no package.json yet — skipping"
fi

# ───────────────────────── 4. environment ─────────────────────────
step "4/8 Environment (.env files)"
cd "$BACKEND"
FRESH_ENV=0
if [ ! -s .env ]; then cp .env.example .env; FRESH_ENV=1; ok "Created backend/.env from .env.example"; fi
export FRESH_ENV
FRONTEND_ORIGIN="http://${PUBLIC_HOST}:${FRONTEND_PORT}"
BACKEND_URL="http://${PUBLIC_HOST}:${PORT}"
"$VPY" - "$FRONTEND_ORIGIN" <<'PY'
import os, re, secrets, sys
from urllib.parse import quote_plus, unquote_plus

frontend_origin = sys.argv[1]
path = ".env"
text = open(path).read()

def get(k):
    m = re.search(rf"^{k}=(.*)$", text, re.M)
    return m.group(1).strip() if m else None

def put(k, v):
    global text
    if re.search(rf"^{k}=", text, re.M):
        text = re.sub(rf"^{k}=.*$", lambda _: f"{k}={v}", text, flags=re.M)
    else:
        text += ("" if text.endswith("\n") else "\n") + f"{k}={v}\n"

if not get("JWT_SECRET_KEY"):
    put("JWT_SECRET_KEY", secrets.token_hex(32))
    print("  generated JWT_SECRET_KEY")

def mysql_username(u):
    m = re.match(r"^mysql\+pymysql://([^:@/]+)", u)
    return unquote_plus(m.group(1)) if m else None

url = get("DATABASE_URL") or ""
current_user = mysql_username(url)
# Rewrite DATABASE_URL whenever it's unset, still the sqlite default, or a
# MySQL URL whose username no longer matches DB_USER -- so re-running
# install.sh with different DB_* values (e.g. switching root -> app_user)
# actually takes effect instead of leaving a stale URL from an earlier run.
switch = os.environ["USE_SQLITE"] != "1" and (
    not url
    or url.startswith("sqlite")
    or (current_user is not None and current_user != os.environ["DB_USER"])
)
if switch:
    user = quote_plus(os.environ["DB_USER"])
    pw = quote_plus(os.environ["DB_PASS"])
    cred = user + (":" + pw if pw else "")
    put("DATABASE_URL", f"mysql+pymysql://{cred}@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_NAME']}")
    print("  DATABASE_URL set to MySQL")

# Without this, CORSMiddleware's allow_origins stays [] (the
# .env.example default) and every browser request the frontend makes is
# blocked by CORS even though the two services can reach each other fine
# over plain HTTP -- the "frontend can't talk to backend" symptom this
# script exists to prevent. Only fill it in when unset so a
# manually-customized value (e.g. a real domain in production) is never
# clobbered by a re-run.
if not get("CORS_ORIGINS"):
    put("CORS_ORIGINS", frontend_origin)
    print(f"  CORS_ORIGINS set to {frontend_origin}")

open(path, "w").write(text)
PY
chmod 600 .env 2>/dev/null || true
ok "backend/.env ready"

if [ "$HAS_FRONTEND" = "1" ]; then
  cd "$FRONTEND"
  if [ ! -s .env ]; then cp .env.example .env; ok "Created frontend/.env from .env.example"; fi
  "$VPY" - "$BACKEND_URL" <<'PY'
import re, sys

backend_url = sys.argv[1]
path = ".env"
text = open(path).read()

def get(k):
    m = re.search(rf"^{k}=(.*)$", text, re.M)
    return m.group(1).strip() if m else None

def put(k, v):
    global text
    if re.search(rf"^{k}=", text, re.M):
        text = re.sub(rf"^{k}=.*$", lambda _: f"{k}={v}", text, flags=re.M)
    else:
        text += ("" if text.endswith("\n") else "\n") + f"{k}={v}\n"

# Vite inlines VITE_API_URL at build time -- if this is left unset (or
# stuck on the .env.example placeholder while PORT was overridden), the
# built/dev frontend silently calls its own origin instead of the
# backend and every API request 404s or hits the wrong server. Only
# fill it in when unset, same rule as backend/.env above, so a
# manually-customized value survives a re-run.
if not get("VITE_API_URL"):
    put("VITE_API_URL", backend_url)
    print(f"  VITE_API_URL set to {backend_url}")

open(path, "w").write(text)
PY
  ok "frontend/.env ready"
fi

# ───────────────────────── 5. build frontend ─────────────────────────
if [ "$HAS_FRONTEND" = "1" ] && [ "$FRONTEND_MODE" = "preview" ]; then
  step "5/8 Build frontend"
  ( cd "$FRONTEND" && npm run build )
  ok "Frontend built"
else
  step "5/8 Build frontend"
  ok "Skipped (dev server mode)"
fi

# ───────────────────────── 6. database ─────────────────────────
step "6/8 Database"
cd "$BACKEND"
"$VPY" - <<'PY'
import re
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

m = re.search(r"^DATABASE_URL=(.*)$", open(".env").read(), re.M)
url = make_url(m.group(1).strip())
if url.get_backend_name() == "mysql":
    name = url.database
    eng = create_engine(url.set(database=None), isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as c:
            c.execute(text(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    except Exception as e:
        raise SystemExit(
            f"  Cannot reach MySQL at {url.host}:{url.port} as {url.username}: {getattr(e, 'orig', e)}\n"
            "  Start MySQL/XAMPP and check DB_* values (or re-run with USE_SQLITE=1)."
        )
    print(f"  MySQL database `{name}` ready")
else:
    print(f"  {url.get_backend_name()} database — no server setup needed")
PY
BEFORE="$("$VPY" -m alembic current 2>&1 | tail -1)" || true
UPGRADE_OUT="$("$VPY" -m alembic upgrade head 2>&1)" || { echo "$UPGRADE_OUT"; die "alembic upgrade head failed"; }
if echo "$UPGRADE_OUT" | grep -q "Running upgrade"; then
  echo "$UPGRADE_OUT" | grep "Running upgrade" | sed 's/^/  /'
  ok "Migrations applied"
else
  ok "Migrations already up to date ($BEFORE) — nothing to run"
fi

USERS="$("$VPY" - <<'PY'
from app.core.database import SessionLocal
from app.models.user import User
db = SessionLocal()
print(db.query(User).count())
db.close()
PY
)"
if [ "$USERS" = "0" ]; then
  if [ -t 0 ]; then
    warn "No users yet — creating the first organisation + admin"
    "$VPY" -m scripts.seed_admin
  else
    warn "No users yet — run later:  cd backend && .venv/bin/python -m scripts.seed_admin"
  fi
else
  ok "$USERS user(s) already exist — skipping admin seed"
fi

# ───────────────────────── 7. pm2 ─────────────────────────
step "7/8 Start with pm2"
# Both processes are declared in one ecosystem file instead of two
# independent ad-hoc `pm2 start` invocations, so `pm2 start/restart/stop
# ecosystem.config.json` (or `pm2 restart all` after `pm2 save`) manages
# backend + frontend together as one unit rather than two processes that
# drift apart. Regenerated every run so path/port overrides always take
# effect; it holds only local absolute paths, so it's gitignored, not
# committed.
ECOSYSTEM="$APP_DIR/ecosystem.config.json"
"$VPY" - "$ECOSYSTEM" "$APP_NAME" "$BACKEND" "$VPY" "$HOST" "$PORT" "$WORKERS" \
  "$HAS_FRONTEND" "$FRONTEND_APP_NAME" "$FRONTEND" "$FRONTEND_MODE" "$FRONTEND_PORT" <<'PY'
import json, sys

(ecosystem, app_name, backend, vpy, host, port, workers,
 has_frontend, frontend_app_name, frontend, frontend_mode, frontend_port) = sys.argv[1:13]

apps = [{
    "name": app_name,
    "cwd": backend,
    "script": vpy,
    "interpreter": "none",
    "args": ["-m", "uvicorn", "app.main:app", "--host", host, "--port", port, "--workers", workers],
    "autorestart": True,
}]
if has_frontend == "1":
    vite_script = "preview" if frontend_mode == "preview" else "dev"
    apps.append({
        "name": frontend_app_name,
        "cwd": frontend,
        "script": "npm",
        "args": ["run", vite_script, "--", "--host", host, "--port", frontend_port, "--strictPort"],
        "autorestart": True,
    })

with open(ecosystem, "w") as f:
    json.dump({"apps": apps}, f, indent=2)
PY
ok "Wrote $(basename "$ECOSYSTEM")"

pm2 delete "$APP_NAME" >/dev/null 2>&1 || true
[ "$HAS_FRONTEND" = "1" ] && { pm2 delete "$FRONTEND_APP_NAME" >/dev/null 2>&1 || true; }
pm2 start "$ECOSYSTEM"
pm2 save --force >/dev/null
ok "pm2 started from ecosystem.config.json"

# ───────────────────────── 8. health check ─────────────────────────
step "8/8 Health check"
pm2_state() {
  pm2 jlist 2>/dev/null | node -e '
    let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
      let l=[];try{l=JSON.parse(s.slice(s.indexOf("[")))}catch(e){}
      const p=l.find(x=>x.name===process.argv[1]);
      if(!p){console.log("missing");process.exit(1)}
      const e=p.pm2_env||{};
      console.log(e.status+" (restarts: "+(e.restart_time||0)+")");
      process.exit(e.status==="online"&&(e.restart_time||0)<3?0:1);});' "$1"
}
fail_logs() { pm2 logs "$1" --lines 40 --nostream 2>&1 | tail -60 || true; }

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:$PORT/health}"
HEALTHY=""
for ((i = 0; i < HEALTH_TIMEOUT; i += 2)); do
  body="$(curl -s -m 5 "$HEALTH_URL" 2>/dev/null || true)"
  case "$body" in *'"ok"'*) HEALTHY=1; break ;; esac
  sleep 2
done
if [ -z "$HEALTHY" ]; then fail_logs "$APP_NAME"; die "No healthy response from $HEALTH_URL within ${HEALTH_TIMEOUT}s"; fi
ok "GET /health -> $body"

sleep 2
STATE="$(pm2_state "$APP_NAME")" || { fail_logs "$APP_NAME"; die "pm2 process '$APP_NAME' unhealthy: $STATE"; }
ok "pm2 ($APP_NAME): $STATE"

if [ "$HAS_FRONTEND" = "1" ]; then
  FSTATE="$(pm2_state "$FRONTEND_APP_NAME")" || { fail_logs "$FRONTEND_APP_NAME"; die "pm2 process '$FRONTEND_APP_NAME' unhealthy: $FSTATE"; }
  ok "pm2 ($FRONTEND_APP_NAME): $FSTATE"
  FCODE="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$FRONTEND_PORT/" 2>/dev/null || true)"
  case "$FCODE" in 2*|3*) ok "Frontend responding on :$FRONTEND_PORT ($FCODE)" ;; *) warn "Frontend on :$FRONTEND_PORT returned $FCODE — check pm2 logs $FRONTEND_APP_NAME" ;; esac
fi

MIGR="$(cd "$BACKEND" && "$VPY" -m alembic current 2>&1 | tail -1)"
case "$MIGR" in *"(head)"*) ok "DB schema at head: $MIGR" ;; *) die "DB schema not at head: $MIGR" ;; esac

printf '\n\033[1;32mDeploy complete\033[0m  %s @ %s\n' "$APP_NAME" "$(git -C "$APP_DIR" rev-parse --short HEAD)"
printf '  Backend:  %s  (docs: /docs)\n' "$BACKEND_URL"
[ "$HAS_FRONTEND" = "1" ] && printf '  Frontend: %s\n' "$FRONTEND_ORIGIN"
echo "  Manage both processes together:  pm2 restart ecosystem.config.json   # or: pm2 restart all"
echo "  Survive reboots (once):  pm2 startup   # then run the command it prints"
