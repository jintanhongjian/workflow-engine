#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
CONTROL_SCRIPT="$PROJECT_DIR/service_control.sh"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/monitor.log"
CELERY_APP="workflow-engine"

INTERVAL_SECONDS="${MONITOR_INTERVAL:-60}"
RUN_ONCE="${MONITOR_ONCE:-0}"
SELF_HEAL="${MONITOR_SELF_HEAL:-1}"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR" || exit 1

timestamp() {
    date "+%Y-%m-%d %H:%M:%S"
}

log() {
    local level="$1"
    local message="$2"
    printf "[%s] [%s] %s\n" "$(timestamp)" "$level" "$message" | tee -a "$LOG_FILE" >/dev/null
}

is_running() {
    local pattern="$1"
    pgrep -f "$pattern" >/dev/null 2>&1
}

rotate_old_logs() {
    find "$LOG_DIR" -name "*.log" -mtime +7 -type f -delete 2>/dev/null || true
}

restart_component() {
    local component="$1"
    log "WARN" "$component stopped, trying restart via service_control.sh start"
    "$CONTROL_SCRIPT" start >>"$LOG_FILE" 2>&1
}

check_component() {
    local name="$1"
    local pattern="$2"

    if is_running "$pattern"; then
        log "INFO" "$name running"
        return 0
    fi

    log "ERROR" "$name not running"
    if [ "$SELF_HEAL" = "1" ]; then
        restart_component "$name"
    fi
    return 1
}

monitor_once() {
    check_component "Redis" "redis-server"
    check_component "Gunicorn" "gunicorn ${CELERY_APP}\.wsgi"
    check_component "Celery Worker" "celery -A ${CELERY_APP} worker"
    check_component "Celery Beat" "celery -A ${CELERY_APP} beat"
    rotate_old_logs
}

show_help() {
    cat <<EOF
Usage: $0 [--once] [--interval SECONDS] [--no-heal]

Options:
  --once               Run one monitoring cycle and exit
  --interval SECONDS   Monitoring interval in seconds (default: ${INTERVAL_SECONDS})
  --no-heal            Disable automatic restart (only log status)
  --status             Print current status and exit
  --help               Show help

Environment:
  MONITOR_INTERVAL     Same as --interval
  MONITOR_ONCE=1       Same as --once
  MONITOR_SELF_HEAL=0  Same as --no-heal
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --once)
            RUN_ONCE="1"
            shift
            ;;
        --interval)
            INTERVAL_SECONDS="$2"
            shift 2
            ;;
        --no-heal)
            SELF_HEAL="0"
            shift
            ;;
        --status)
            monitor_once
            exit 0
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

if ! [[ "$INTERVAL_SECONDS" =~ ^[0-9]+$ ]] || [ "$INTERVAL_SECONDS" -le 0 ]; then
    echo "Invalid interval: $INTERVAL_SECONDS"
    exit 1
fi

log "INFO" "monitor started (once=$RUN_ONCE, interval=${INTERVAL_SECONDS}s, self_heal=$SELF_HEAL)"

if [ "$RUN_ONCE" = "1" ]; then
    monitor_once
    exit 0
fi

while true; do
    monitor_once
    sleep "$INTERVAL_SECONDS"
done