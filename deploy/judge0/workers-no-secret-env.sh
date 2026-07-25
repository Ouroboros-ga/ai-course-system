#!/bin/bash
set -euo pipefail

# Judge0's upstream worker script logs every exported variable while writing
# /api/environment.  That includes database and API credentials.  Isolate only
# needs execution limits there, so persist a filtered environment instead.
source /api/scripts/load-config
env | grep -Ev '^(AUTHN_TOKEN|AUTHZ_TOKEN|REDIS_PASSWORD|POSTGRES_PASSWORD|SECRET_KEY_BASE)=' \
  | sudo tee /api/environment >/dev/null

run_resque=1
resque_pid=0
scheduler_pid=0

date_now() {
    date +"%Y-%m-%d-%H-%M-%S"
}

exit_gracefully() {
    echo "[$(date_now)] Killing workers."
    run_resque=0
    kill -SIGQUIT "$(pgrep -P "$resque_pid")" 2>/dev/null || true
    kill -SIGTERM "$resque_pid" 2>/dev/null || true
}

trap exit_gracefully SIGTERM SIGINT
mkdir -p tmp/pids >/dev/null 2>&1
while [[ $run_resque -eq 1 ]]; do
    echo "[$(date_now)] Starting scheduler."
    if ! ps -p "$scheduler_pid" >/dev/null 2>&1; then
        rake resque:scheduler &
        scheduler_pid=$!
    fi

    rm -f tmp/pids/resque.pid
    echo "[$(date_now)] Starting workers."
    rails resque:workers &
    resque_pid=$!
    while ps -p "$resque_pid" >/dev/null 2>&1; do sleep 1s; done
    echo "[$(date_now)] Workers are stopped."
done
