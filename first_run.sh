#!/usr/bin/env bash
# first_run.sh — the ONE command to run on a brand-new server, once.
#
#   bash first_run.sh
#
# Division of labor with install.sh (no step is done by both):
#   first_run.sh does ONLY what install.sh categorically cannot: install
#   system packages that need root/apt (git, curl, Node, Python, the
#   MariaDB *server* itself) and provision the MariaDB *account*
#   (CREATE USER/DATABASE/GRANT). Everything else — pulling the repo to
#   latest, the venv, npm deps, writing backend/.env, alembic migrate,
#   pm2, and the health-check loop — stays install.sh's job, run exactly
#   once, right here in step 8. That's also why first_run.sh's own git
#   step below only clones if the repo is completely absent; it never
#   fetches/pulls, because install.sh's very next step does exactly that.
#
# What it does, in order:
#   1. Detect package manager / privilege level
#   2. Ensure git + curl are present
#   3. Check Node.js + npm + Python versions, install what's missing (apt only)
#   4. Clone the repo if it isn't present yet (install.sh pulls it to latest)
#   5. Check/install MariaDB, verify its version, confirm it's reachable
#   6. Resolve DB_NAME/DB_USER/DB_PASS — reuse them if they already work
#      (including reusing whatever password is already in backend/.env
#      from a previous run, so re-running never rotates a working
#      password), otherwise create the database + user. Never a
#      hardcoded password.
#   7. Resolve PORT/FRONTEND_PORT and confirm they're actually free
#   8. Hand off to install.sh (git pull, python venv, npm deps, .env,
#      alembic migrate, pm2 start, loopback health-check loop)
#   9. Post-install: confirm the backend is reachable via PUBLIC_HOST
#      specifically (install.sh already proved it on 127.0.0.1)
#  10. Check the CORS header actually matches what was configured
#
# Safe to re-run: every step checks state before changing anything.
#
# Env overrides (all optional — you'll be prompted for what's missing on
# an interactive terminal; on a non-interactive one, defaults are used):
#   REPO_URL BRANCH APP_DIR
#   DB_HOST DB_PORT DB_NAME DB_USER DB_PASS   USE_SQLITE=1 to skip DB setup
#   PORT FRONTEND_PORT HOST PUBLIC_HOST
#   MIN_NODE_MAJOR (default 20)   NODE_INSTALL_MAJOR (default 22, used only
#     when Node is completely absent and gets installed via NodeSource)
#   MIN_MARIADB_VERSION (default 10.4 — warns, does not block, if older)
#   MYSQL_ROOT_PASSWORD   set this if root@localhost needs a password to
#     administer MariaDB (Debian/Ubuntu defaults to unix_socket auth, so
#     this is usually unnecessary — sudo covers it)
#   HEALTH_TIMEOUT   forwarded as-is to install.sh's own health-check loop
#   NONINTERACTIVE=1   never prompt; fail loudly instead of asking
set -Eeuo pipefail

REPO_URL="${REPO_URL:-https://github.com/BT-Rajan/jdk_erp.git}"
BRANCH="${BRANCH:-main}"
HOST="${HOST:-0.0.0.0}"
PUBLIC_HOST="${PUBLIC_HOST:-localhost}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
USE_SQLITE="${USE_SQLITE:-0}"
MIN_NODE_MAJOR="${MIN_NODE_MAJOR:-20}"
NODE_INSTALL_MAJOR="${NODE_INSTALL_MAJOR:-22}"
MIN_MARIADB_VERSION="${MIN_MARIADB_VERSION:-10.4}"
NONINTERACTIVE="${NONINTERACTIVE:-0}"
export USE_SQLITE HOST PUBLIC_HOST

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }
info() { printf '\033[1;34m  i %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  ✘ %s\033[0m\n' "$*" >&2; exit 1; }
trap 'die "Failed at line $LINENO: $BASH_COMMAND"' ERR
have() { command -v "$1" >/dev/null 2>&1; }
is_tty() { [ "$NONINTERACTIVE" != "1" ] && [ -t 0 ]; }

# Prompt with a default; falls straight through to the default when not
# on an interactive terminal or NONINTERACTIVE=1, so this script works
# unattended (e.g. cloud-init) as well as by hand. read's own -p prompt
# never pollutes this function's captured stdout (verified: it's written
# to the terminal directly, not mixed into what $(...) picks up).
ask() {
  local prompt="$1" default="$2" reply
  if is_tty; then
    read -rp "  $prompt [$default]: " reply || true
    printf '%s\n' "${reply:-$default}"
  else
    printf '%s\n' "$default"
  fi
}
ask_secret() {
  local prompt="$1" reply
  if is_tty; then
    read -rsp "  $prompt (leave blank to auto-generate): " reply || true
    printf '\n' >&2
    printf '%s\n' "$reply"
  else
    printf '\n'
  fi
}

version_ge() { # version_ge A B -> true if A >= B, dotted-numeric compare
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]
}
valid_ident() { [[ "$1" =~ ^[A-Za-z0-9_]+$ ]]; } # safe as a bare SQL identifier
ask_ident() { # ask_ident varname prompt default
  local __v="$1" prompt="$2" default="$3" val
  val="$(ask "$prompt" "$default")"
  while ! valid_ident "$val"; do
    warn "'$val' must contain only letters, numbers, underscore"
    is_tty || die "${__v} must match ^[A-Za-z0-9_]+\$ (got '$val')"
    val="$(ask "$prompt" "$default")"
  done
  printf -v "$__v" '%s' "$val"
}
sql_escape() { # escape a value for safe use inside a single-quoted SQL literal
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\'/\\\'}"
  printf '%s' "$s"
}
urldecode() { # decode a Python urllib.parse.quote_plus-style value
  local data="${1//+/ }"
  printf '%b' "${data//%/\\x}"
}
is_valid_port() { [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }

# ───────────────────────── 1. privilege / package manager ─────────────────────────
step "1/10 Privilege & package manager"
if [ "$(id -u)" = "0" ]; then
  SUDO=""
elif have sudo; then
  SUDO="sudo"
else
  SUDO=""
  warn "Not root and no sudo — dependency installation steps will be skipped if anything is missing"
fi
PKG=""
have apt-get && PKG="apt"
if [ -z "$PKG" ]; then
  warn "No apt-get found — this script auto-installs missing packages on Debian/Ubuntu only."
  warn "On other distros, install git/curl/node/npm/mariadb yourself and re-run."
else
  ok "apt-based system detected"
fi
apt_install() { # apt_install pkg1 pkg2 ...
  [ "$PKG" = "apt" ] || { warn "Cannot auto-install $*: no supported package manager"; return 1; }
  [ -n "$SUDO" ] || [ "$(id -u)" = "0" ] || { warn "Cannot auto-install $*: need root or sudo"; return 1; }
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq "$@" >/dev/null
}

# ───────────────────────── 2. git + curl ─────────────────────────
step "2/10 git & curl"
for tool in git curl; do
  if ! have "$tool"; then
    warn "$tool not found — installing"
    apt_install "$tool" || die "$tool is required and could not be auto-installed"
  fi
done
ok "git $(git --version | awk '{print $3}'), curl $(curl --version | head -1 | awk '{print $2}')"

# ───────────────────────── 3. Node.js + npm ─────────────────────────
step "3/10 Node.js, npm & Python"
node_major() { node -e 'console.log(process.versions.node.split(".")[0])' 2>/dev/null; }
if ! have node; then
  warn "Node.js not found — installing Node ${NODE_INSTALL_MAJOR}.x via NodeSource"
  if [ "$PKG" = "apt" ]; then
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_INSTALL_MAJOR}.x" | $SUDO bash - >/dev/null
    apt_install nodejs || die "Node.js install failed"
  else
    die "Node.js is required — install it manually (e.g. via nvm) and re-run"
  fi
fi
have npm || die "npm not found — Node.js install looks incomplete"
NM="$(node_major)"
if [ -z "$NM" ] || [ "$NM" -lt "$MIN_NODE_MAJOR" ]; then
  die "Node $(node -v) found, need >= v${MIN_NODE_MAJOR}. Upgrade Node (nvm or NodeSource) and re-run — auto-upgrading an existing Node install is not done automatically, in case other apps on this box depend on it."
fi
ok "Node $(node -v), npm v$(npm -v) — compatible (>= v${MIN_NODE_MAJOR})"

# install.sh itself hard-requires Python 3.11+ (its very first check) —
# checked here too so a missing/old Python fails fast with an install
# attempt, instead of first_run.sh sailing through everything else only
# for install.sh to die on its first line.
py_ok() { [ -n "${PYBIN:-}" ] && "$PYBIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; }
PYBIN="$(command -v python3 || command -v python || true)"
if ! py_ok; then
  warn "Python 3.11+ not found$( [ -n "$PYBIN" ] && printf ' (found %s)' "$("$PYBIN" -V 2>&1)" ) — installing python3.11"
  if [ "$PKG" = "apt" ]; then
    apt_install python3.11 python3.11-venv python3-pip || die "Python 3.11 install failed"
    PYBIN="$(command -v python3.11 || command -v python3)"
  else
    die "Python 3.11+ is required — install it manually and re-run"
  fi
fi
py_ok || die "Python 3.11+ still not available after install attempt"
ok "Python $("$PYBIN" -V 2>&1)"

# ───────────────────────── 4. clone the repo (if it isn't already) ─────────────────────────
step "4/10 Repository"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -z "${APP_DIR:-}" ]; then
  if git -C "$SCRIPT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    APP_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
  else
    APP_DIR="$SCRIPT_DIR/jdk_erp"
  fi
fi
if [ -d "$APP_DIR/.git" ]; then
  cd "$APP_DIR"
  ok "Already present at $APP_DIR ($(git rev-parse --short HEAD)) — install.sh pulls it to latest next, so nothing to do here"
else
  info "Not present yet — cloning $REPO_URL ($BRANCH) into $APP_DIR"
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  cd "$APP_DIR"
  ok "Cloned $(git rev-parse --short HEAD)"
fi
[ -f "$APP_DIR/install.sh" ] || die "install.sh not found in $APP_DIR — is REPO_URL/BRANCH correct?"

# ───────────────────────── 5. MariaDB ─────────────────────────
step "5/10 MariaDB"
if [ "$USE_SQLITE" = "1" ]; then
  ok "USE_SQLITE=1 — skipping MariaDB entirely"
else
  if ! have mariadb && ! have mysql; then
    warn "No MariaDB/MySQL client found — installing mariadb-server"
    apt_install mariadb-server mariadb-client || die "MariaDB install failed — install it manually or set USE_SQLITE=1"
  fi
  # Make sure the service is actually running.
  if have systemctl; then
    if ! systemctl is-active --quiet mariadb 2>/dev/null; then
      warn "mariadb service not running — starting it"
      $SUDO systemctl enable --now mariadb || die "Could not start mariadb via systemctl"
    fi
  elif have service; then
    service mariadb status >/dev/null 2>&1 || { $SUDO service mariadb start || die "Could not start mariadb"; }
  else
    warn "No systemctl/service found — make sure MariaDB is running yourself"
  fi
  SERVER_BIN="$(command -v mariadbd || command -v mysqld || true)"
  if [ -n "$SERVER_BIN" ]; then
    SRV_VER="$("$SERVER_BIN" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
    if [ -n "$SRV_VER" ]; then
      if version_ge "$SRV_VER" "$MIN_MARIADB_VERSION"; then
        ok "MariaDB server $SRV_VER (>= $MIN_MARIADB_VERSION)"
      else
        warn "MariaDB server $SRV_VER is older than the recommended $MIN_MARIADB_VERSION — proceeding anyway, but consider upgrading"
      fi
    else
      warn "Could not parse MariaDB server version — proceeding anyway"
    fi
  else
    warn "Could not locate mariadbd/mysqld binary to check version — proceeding anyway"
  fi
  # Reachability check on DB_HOST:DB_PORT, retried briefly in case the
  # service was just started above and needs a moment to accept
  # connections (mainly relevant on non-systemd/container init paths).
  MYSQL_BIN="$(command -v mariadb || command -v mysql)"
  REACHABLE=0
  for attempt in 1 2 3 4 5; do
    if "$MYSQL_BIN" -h "$DB_HOST" -P "$DB_PORT" --connect-timeout=5 -e "SELECT 1;" >/dev/null 2>&1; then
      REACHABLE=1; break
    fi
    if "$MYSQL_BIN" -h "$DB_HOST" -P "$DB_PORT" --connect-timeout=5 -u nonexistent_probe_user -e "SELECT 1;" 2>&1 \
       | grep -qE "Access denied|1045"; then
      # A clean auth rejection still proves the server is up and reachable.
      REACHABLE=1; break
    fi
    [ "$attempt" -lt 5 ] && sleep 2
  done
  [ "$REACHABLE" = "1" ] || die "Cannot reach MariaDB at ${DB_HOST}:${DB_PORT} after several attempts. Check it's running and listening on that host/port, or set USE_SQLITE=1."
  ok "MariaDB reachable at ${DB_HOST}:${DB_PORT}"
fi

# ───────────────────────── 6. DB user + database ─────────────────────────
step "6/10 Database user & schema"
if [ "$USE_SQLITE" = "1" ]; then
  ok "USE_SQLITE=1 — nothing to provision"
else
  ask_ident DB_NAME "Database name" "${DB_NAME:-jdk_erp}"
  ask_ident DB_USER "Database user" "${DB_USER:-app_user}"

  ENV_FILE="$APP_DIR/backend/.env"
  reuse_pass_from_env() {
    # If backend/.env already has a MySQL DATABASE_URL for this exact
    # DB_USER/DB_HOST/DB_PORT/DB_NAME, reuse its password instead of
    # generating a new one -- keeps re-runs idempotent (no silent
    # password rotation every time this script runs unattended).
    [ -f "$ENV_FILE" ] || return 1
    local line url
    line="$(grep -m1 '^DATABASE_URL=' "$ENV_FILE" 2>/dev/null || true)"
    url="${line#DATABASE_URL=}"
    if [[ "$url" =~ ^mysql\+pymysql://([^:@]+):([^@]+)@([^:/]+):([0-9]+)/([^/?[:space:]]+)$ ]]; then
      local u="${BASH_REMATCH[1]}" p="${BASH_REMATCH[2]}" h="${BASH_REMATCH[3]}" pt="${BASH_REMATCH[4]}" n="${BASH_REMATCH[5]}"
      if [ "$u" = "$DB_USER" ] && [ "$h" = "$DB_HOST" ] && [ "$pt" = "$DB_PORT" ] && [ "$n" = "$DB_NAME" ]; then
        urldecode "$p"
        return 0
      fi
    fi
    return 1
  }

  GENERATED_PASS=0
  REUSED_PASS=0
  if [ -z "${DB_PASS:-}" ]; then
    if FOUND_PASS="$(reuse_pass_from_env)" && [ -n "$FOUND_PASS" ]; then
      DB_PASS="$FOUND_PASS"
      REUSED_PASS=1
    fi
  fi
  if [ -z "${DB_PASS:-}" ]; then
    DB_PASS="$(ask_secret "Database password for $DB_USER")"
    if [ -z "$DB_PASS" ]; then
      DB_PASS="$(openssl rand -hex 16 2>/dev/null || head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
      GENERATED_PASS=1
    fi
  fi
  [ "$REUSED_PASS" = "1" ] && info "Reusing the password already on file in backend/.env for '$DB_USER'"

  MYSQL_BIN="$(command -v mariadb || command -v mysql)"

  db_user_ok() {
    MYSQL_PWD="$DB_PASS" "$MYSQL_BIN" -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" \
      --connect-timeout=5 -e "USE \`$DB_NAME\`;" >/dev/null 2>&1
  }

  ADMIN_MYSQL_ERR=""
  admin_mysql() {
    local out
    if [ -z "${MYSQL_ROOT_PASSWORD:-}" ] && { [ -n "$SUDO" ] || [ "$(id -u)" = "0" ]; }; then
      if out="$($SUDO "$MYSQL_BIN" -e "$1" 2>&1)"; then return 0; fi
      ADMIN_MYSQL_ERR="$out"
    fi
    if [ -n "${MYSQL_ROOT_PASSWORD:-}" ]; then
      if out="$(MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$MYSQL_BIN" -h "$DB_HOST" -P "$DB_PORT" -u root -e "$1" 2>&1)"; then return 0; fi
      ADMIN_MYSQL_ERR="$out"
    fi
    return 1
  }

  if db_user_ok; then
    ok "Database '$DB_NAME' and user '$DB_USER' already exist and are reachable — reusing them"
  else
    info "Database/user not found or not reachable with those credentials — creating"
    SQL_PASS="$(sql_escape "$DB_PASS")"
    SQL="
      CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
      CREATE USER IF NOT EXISTS '$DB_USER'@'%' IDENTIFIED BY '$SQL_PASS';
      CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$SQL_PASS';
      ALTER USER '$DB_USER'@'%' IDENTIFIED BY '$SQL_PASS';
      ALTER USER '$DB_USER'@'localhost' IDENTIFIED BY '$SQL_PASS';
      GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'%';
      GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
      FLUSH PRIVILEGES;
    "
    admin_mysql "$SQL" || die "Could not administer MariaDB as root: ${ADMIN_MYSQL_ERR:-no root access available}. Either run this script with sudo, or set MYSQL_ROOT_PASSWORD."
    db_user_ok || die "Created '$DB_USER'/'$DB_NAME' but still can't connect — check DB_HOST/DB_PORT and any remote-access (bind-address) restrictions on MariaDB."
    ok "Created database '$DB_NAME' and user '$DB_USER'"
    [ "$GENERATED_PASS" = "1" ] && warn "Generated password for '$DB_USER': $DB_PASS  (also saved into backend/.env — chmod 600)"
  fi
  export DB_HOST DB_PORT DB_NAME DB_USER DB_PASS
fi

# ───────────────────────── 7. ports ─────────────────────────
step "7/10 Ports"
port_free() { # returns success (0) if the port is free, 1 if something's listening
  local port="$1"
  if have ss; then
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[.:]${port}\$"; then
      return 1
    fi
  else
    if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
      exec 3<&- 3>&-
      return 1
    fi
  fi
  return 0
}
resolve_port() { # resolve_port varname prompt default
  local __v="$1" prompt="$2" default="$3" p
  p="$(ask "$prompt" "$default")"
  while true; do
    if ! is_valid_port "$p"; then
      warn "'$p' isn't a valid port number (1-65535)"
      is_tty || die "${__v} must be a valid port number (1-65535), got '$p'"
      p="$(ask "$prompt" "$default")"
      continue
    fi
    port_free "$p" && break
    warn "Port $p is already in use"
    is_tty || die "Port $p is in use and this is a non-interactive run — set ${__v} to a free port"
    p="$(ask "$prompt (busy, pick another)" "$((p + 1))")"
  done
  printf -v "$__v" '%s' "$p"
}
resolve_port PORT "Backend port" "${PORT:-8989}"
resolve_port FRONTEND_PORT "Frontend port" "${FRONTEND_PORT:-7173}"
export PORT FRONTEND_PORT
ok "Backend will use :$PORT, frontend :$FRONTEND_PORT — both confirmed free"

# ───────────────────────── 8. hand off to install.sh ─────────────────────────
step "8/10 App install (install.sh: git pull, venv, npm deps, .env, migrations, pm2)"
bash "$APP_DIR/install.sh" || die "install.sh failed — see output above"

# ───────────────────────── 9. post-install verification ─────────────────────────
step "9/10 Post-install checks"
BACKEND_URL="http://${PUBLIC_HOST}:${PORT}"
FRONTEND_URL="http://${PUBLIC_HOST}:${FRONTEND_PORT}"

# install.sh's own step 8/8 already looped on http://127.0.0.1:$PORT/health
# until it was confirmed healthy -- it would have died above otherwise, so
# that fact is already established. The only thing NOT yet proven is
# whether the app is reachable the way a real client actually reaches it:
# via PUBLIC_HOST. A failure here is therefore a DNS/firewall/routing
# question, not evidence the install itself failed -- so this warns
# rather than dying.
info "curl $BACKEND_URL/health"
HEALTH_BODY="$(curl -sS -m 5 "$BACKEND_URL/health" 2>/dev/null || true)"
case "$HEALTH_BODY" in
  *'"ok"'*) ok "Backend healthy via $PUBLIC_HOST: $HEALTH_BODY" ;;
  *) warn "Backend is healthy on 127.0.0.1 (install.sh already confirmed it) but not reachable via '$PUBLIC_HOST' — check DNS/firewall/security-group rules for that host" ;;
esac

info "curl $FRONTEND_URL/"
FCODE="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$FRONTEND_URL/" || true)"
case "$FCODE" in
  2*|3*) ok "Frontend responding ($FCODE)" ;;
  *) warn "Frontend returned $FCODE — check: pm2 logs" ;;
esac

# ───────────────────────── 10. CORS check ─────────────────────────
step "10/10 CORS check"
CORS_CONFIGURED="$(grep -m1 '^CORS_ORIGINS=' "$APP_DIR/backend/.env" 2>/dev/null | cut -d= -f2- | cut -d, -f1)"
CHECK_ORIGIN="${CORS_CONFIGURED:-$FRONTEND_URL}"
CORS_HEADER="$(curl -sS -m 5 -D - -o /dev/null -H "Origin: $CHECK_ORIGIN" "$BACKEND_URL/health" 2>/dev/null \
  | tr -d '\r' | grep -i '^access-control-allow-origin:' || true)"
if [ -n "$CORS_HEADER" ]; then
  ok "CORS is configured for '$CHECK_ORIGIN' — $CORS_HEADER"
else
  warn "No Access-Control-Allow-Origin header seen for Origin '$CHECK_ORIGIN'."
  warn "The frontend will get CORS errors calling the backend from this origin."
  warn "Fix: set CORS_ORIGINS in backend/.env to '$CHECK_ORIGIN' (or the real domain you'll serve the frontend from) and re-run install.sh."
fi

printf '\n\033[1;32mfirst_run.sh complete\033[0m  %s @ %s\n' "$(basename "$APP_DIR")" "$(git -C "$APP_DIR" rev-parse --short HEAD)"
printf '  Backend:  %s  (docs: /docs)\n' "$BACKEND_URL"
printf '  Frontend: %s\n' "$FRONTEND_URL"
echo "  Re-run any time — every step is idempotent. For app-only updates later, 'bash install.sh' alone is enough."
