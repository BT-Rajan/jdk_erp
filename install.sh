#!/usr/bin/env bash
# install.sh — git pull -> deploy -> DB setup + migrate -> pm2 -> health check
#
#   bash install.sh
#
# Env overrides:
#   BRANCH PORT FRONTEND_PORT HOST WORKERS APP_NAME HEALTH_TIMEOUT
#   DB_HOST DB_PORT DB_NAME DB_USER DB_PASS   MySQL/MariaDB settings, applied when backend/.env is first created
#   USE_SQLITE=1                              keep the .env.example SQLite default instead of switching to MySQL
set -Eeuo pipefail

APP_NAME="${APP_NAME:-jdk_erp}"
FRONTEND_APP_NAME="${FRONTEND_APP_NAME:-${APP_NAME}-frontend}"
REPO_URL="${REPO_URL:-https://github.com/BT-Rajan/jdk_erp.git}"
BRANCH="${BRANCH:-main}"
HOST="${HOST:-0.0.0.0}"
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
step "1/7 Prerequisites"
need git; need curl; need node; need npm
PYBIN="$(command -v python3 || command -v python)" || die "Python 3.11+ not found"
"$PYBIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Python 3.11+ required (found $("$PYBIN" -V 2>&1))"
if ! command -v pm2 >/dev/null 2>&1; then warn "pm2 not found — installing globally"; npm install -g pm2; fi
ok "git, node $(node -v), $("$PYBIN" -V 2>&1), pm2 $(pm2 -v)"

# ───────────────────────── 2. git pull ─────────────────────────
step "2/7 Git pull ($BRANCH)"
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

# ───────────────────────── 3. deploy (deps) ─────────────────────────
step "3/7 Deploy backend dependencies"
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
FRONTEND_MODE=""  # "preview" (built, served via vite preview/serve) or "dev"
if [ -f "$FRONTEND/package.json" ]; then
  HAS_FRONTEND=1
  script_exists() { node -e 'process.exit(((require("./package.json").scripts)||{})[process.argv[1]]?0:1)' "$1"; }
  ( cd "$FRONTEND"
    if [ -f package-lock.json ]; then npm ci || npm install; else npm install; fi
    if script_exists build; then
      npm run build
      echo "FRONTEND_MODE=preview" > .install-sh-mode
    else
      echo "FRONTEND_MODE=dev" > .install-sh-mode
    fi )
  FRONTEND_MODE="$(cut -d= -f2 "$FRONTEND/.install-sh-mode")"; rm -f "$FRONTEND/.install-sh-mode"
  ok "Frontend dependencies installed ($([ "$FRONTEND_MODE" = preview ] && echo built || echo "no build script — will run dev server"))"
else
  warn "frontend/ has no package.json yet — skipping"
fi

# ───────────────────────── 4. environment ─────────────────────────
step "4/7 Environment (backend/.env)"
FRESH_ENV=0
if [ ! -s .env ]; then cp .env.example .env; FRESH_ENV=1; ok "Created .env from .env.example"; fi
export FRESH_ENV
"$VPY" - <<'PY'
import os, re, secrets
from urllib.parse import quote_plus, unquote_plus

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

open(path, "w").write(text)
PY
chmod 600 .env 2>/dev/null || true
ok ".env ready"

# ───────────────────────── 5. database ─────────────────────────
step "5/7 Database"
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

# ───────────────────────── 6. pm2 ─────────────────────────
step "6/7 Start with pm2"
pm2 delete "$APP_NAME" >/dev/null 2>&1 || true
pm2 start "$VPY" --name "$APP_NAME" --cwd "$BACKEND" --interpreter none -- \
  -m uvicorn app.main:app --host "$HOST" --port "$PORT" --workers "$WORKERS"
ok "pm2 process '$APP_NAME' started on $HOST:$PORT"

if [ "$HAS_FRONTEND" = "1" ]; then
  pm2 delete "$FRONTEND_APP_NAME" >/dev/null 2>&1 || true
  if [ "$FRONTEND_MODE" = "preview" ]; then
    pm2 start npm --name "$FRONTEND_APP_NAME" --cwd "$FRONTEND" -- run preview -- --host "$HOST" --port "$FRONTEND_PORT" --strictPort
  else
    pm2 start npm --name "$FRONTEND_APP_NAME" --cwd "$FRONTEND" -- run dev -- --host "$HOST" --port "$FRONTEND_PORT" --strictPort
  fi
  ok "pm2 process '$FRONTEND_APP_NAME' started on $HOST:$FRONTEND_PORT ($FRONTEND_MODE)"
fi
pm2 save --force >/dev/null

# ───────────────────────── 7. health check ─────────────────────────
step "7/7 Health check"
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
if [ -z "$HEALTHY" ]; then fail_logs; die "No healthy response from $HEALTH_URL within ${HEALTH_TIMEOUT}s"; fi
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
printf '  Backend:  http://localhost:%s  (docs: /docs)\n' "$PORT"
[ "$HAS_FRONTEND" = "1" ] && printf '  Frontend: http://localhost:%s\n' "$FRONTEND_PORT"
echo "  Survive reboots (once):  pm2 startup   # then run the command it prints"
