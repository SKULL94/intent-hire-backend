#!/usr/bin/env bash
# Kill whatever is serving the API and start a fresh one.
#
# Usage:
#   ./restart.sh                  # kill, then run in foreground (Ctrl-C stops)
#   ./restart.sh --detach         # kill, then background, logs to .uvicorn.log.err
#   ./restart.sh --stop           # kill only
#   ./restart.sh --port 9000      # different port
#   ./restart.sh --no-reload      # disable auto-reload
#
# Self-contained: no other script needed. Safe to run when nothing is running,
# and safe to run repeatedly.

set -euo pipefail

PORT=8000
DETACH=0
STOP=0
NO_RELOAD=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)      PORT="$2";   shift 2 ;;
        --detach)    DETACH=1;    shift ;;
        --stop)      STOP=1;      shift ;;
        --no-reload) NO_RELOAD=1; shift ;;
        -h|--help)   sed -n '2,11p' "$0"; exit 0 ;;
        *)           echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"

say()  { printf '\033[36m> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m+ %s\033[0m\n' "$*"; }

# Ask the API, don't trust lsof alone. The port's listed owner can be a dead
# parent whose child inherited the socket, so a PID can disappear while the
# port keeps answering.
api_alive() {
    curl -sf -m 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1
}

# Three kinds of process have to die, and matching on "uvicorn" finds only the
# first:
#   1) launchers / reloaders  - cmdline contains "uvicorn ... app.main"
#   2) whatever holds the port
#   3) multiprocessing workers - `uvicorn --reload` spawns these as
#      `python -c "from multiprocessing.spawn import spawn_main; ... parent_pid=N"`
#      so their cmdline never mentions uvicorn. They keep serving the inherited
#      socket after their parent exits.
stop_api() {
    local self=$$ seed=" " pid ppid cmd pass added s

    while read -r pid cmd; do
        [[ "$cmd" == *uvicorn*app.main* ]] && seed+="$pid "
    done < <(ps -axo pid=,command=)

    while read -r pid; do
        [[ -n "$pid" ]] && seed+="$pid "
    done < <(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true)

    # Walk descendants + orphaned spawn_main workers until nothing new joins.
    for pass in 1 2 3 4 5; do
        added=0
        while read -r pid ppid cmd; do
            [[ "$seed" == *" $pid "* ]] && continue
            if [[ "$seed" == *" $ppid "* ]]; then
                seed+="$pid "; added=1; continue
            fi
            # A dead parent breaks the ppid link, but spawn_main workers record
            # the original parent PID in their own cmdline.
            if [[ "$cmd" == *spawn_main* ]]; then
                for s in $seed; do
                    if [[ "$cmd" == *"parent_pid=$s"* ]]; then
                        seed+="$pid "; added=1; break
                    fi
                done
            fi
        done < <(ps -axo pid=,ppid=,command=)
        [[ "$added" -eq 0 ]] && break
    done

    seed="${seed// $self / }"
    if [[ -z "${seed// /}" ]]; then
        echo "    nothing to kill"
        return
    fi

    for pid in $seed; do
        if kill -TERM "$pid" 2>/dev/null; then
            echo "    killed $pid"
        elif kill -0 "$pid" 2>/dev/null; then
            echo "    FAILED $pid"
        else
            echo "    already exited $pid"
        fi
    done

    sleep 1
    for pid in $seed; do
        kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
    done
}

py="$root/.venv/bin/python"
if [[ ! -x "$py" ]]; then
    warn "No virtualenv at .venv - create one, or run scripts/dev.sh first."
    exit 1
fi

if api_alive; then
    say "Server is responding on port $PORT - shutting it down"
else
    say "No server responding on port $PORT (sweeping for orphans anyway)"
fi

for attempt in 1 2 3; do
    stop_api
    sleep 2
    api_alive || break
    say "Still responding after attempt $attempt; retrying"
done

if api_alive; then
    warn "Something is still serving port $PORT and would not die. Inspect with:"
    warn "  ps -axo pid,command | grep uvicorn"
    exit 1
fi
ok "Port $PORT is clear"

if [[ "$STOP" -eq 1 ]]; then
    ok "Stopped. Not restarting (--stop)."
    exit 0
fi

if [[ ! -f "$root/.env" ]]; then
    warn "No .env file - app/config.py falls back to a localhost DATABASE_URL and will fail."
    exit 1
fi

uvicorn_args=(-m uvicorn app.main:app --host 0.0.0.0 --port "$PORT")
[[ "$NO_RELOAD" -eq 0 ]] && uvicorn_args+=(--reload)

if [[ "$DETACH" -eq 1 ]]; then
    out_log="$root/.uvicorn.log"
    err_log="$root/.uvicorn.log.err"
    say "Starting detached"
    nohup "$py" "${uvicorn_args[@]}" >"$out_log" 2>"$err_log" &
    pid=$!
    disown "$pid" 2>/dev/null || true

    for i in $(seq 1 30); do
        if api_alive; then
            ok "Server up on http://localhost:$PORT  (PID $pid)"
            curl -s "http://127.0.0.1:$PORT/health"; echo
            ok "Logs:  tail -f .uvicorn.log.err"
            ok "Stop:  ./restart.sh --stop"
            exit 0
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            warn "Server exited during startup. Last lines:"
            [[ -f "$err_log" ]] && tail -n 20 "$err_log"
            exit 1
        fi
        sleep 1
    done
    warn "Server did not answer /health within 30s. Last lines:"
    [[ -f "$err_log" ]] && tail -n 20 "$err_log"
    exit 1
else
    say "Starting on http://localhost:$PORT  (Ctrl-C to stop)"
    exec "$py" "${uvicorn_args[@]}"
fi
