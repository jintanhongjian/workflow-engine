#!/bin/bash

# --- 基础配置 ---
PROJECT_DIR="/home/joehong/workflow-engine"
VENV_PATH="$PROJECT_DIR/.venv"
LOG_DIR="$PROJECT_DIR/logs"
PID_DIR="$PROJECT_DIR/pids"
CELERY_APP="workflow-engine"
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
MONITOR_SCRIPT="$(cd "$(dirname "$0")" && pwd)/monitor_services.sh"
APP_USER="${SUDO_USER:-$(whoami)}"

# --- 组件配置 ---
GUNICORN_PORT=8001
GUNICORN_TIMEOUT=120
GUNICORN_WORKERS=3

# --- 颜色定义 ---
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' 

mkdir -p $LOG_DIR $PID_DIR
cd $PROJECT_DIR

run_as_app_user() {
    if [ "$(whoami)" = "$APP_USER" ]; then
        "$@"
    elif [ "$EUID" -eq 0 ]; then
        sudo -u "$APP_USER" "$@"
    elif sudo -n true 2>/dev/null; then
        sudo -u "$APP_USER" "$@"
    else
        "$@"
    fi
}

kill_by_pattern() {
    local user=$1
    local pattern=$2
    local pids
    pids=$(pgrep -u "$user" -f "$pattern" 2>/dev/null || true)
    for pid in $pids; do
        [ "$pid" = "$$" ] && continue
        [ "$pid" = "$PPID" ] && continue
        kill -9 "$pid" 2>/dev/null || true
    done
}

# 辅助函数：检查进程状态
check_status() {
    local label=$1
    local search_str=$2
    if ps aux | grep "$search_str" | grep -v grep > /dev/null; then
        printf "%-25s [%b  运行中  %b]\n" "$label" "${GREEN}" "${NC}"
    else
        printf "%-25s [%b  已停止  %b]\n" "$label" "${RED}" "${NC}"
    fi
}

case "$1" in
    start)
        echo -e "${BLUE}>>> 准备环境并清理过时锁文件...${NC}"

        # 启动前修复关键文件权限，避免 Gunicorn 无法写日志/pid 导致静默失败
        touch "$LOG_DIR/gunicorn_access.log" "$LOG_DIR/gunicorn_error.log" "$LOG_DIR/celery.log" "$LOG_DIR/beat.log" 2>/dev/null || {
            if [ "$EUID" -eq 0 ]; then
                touch "$LOG_DIR/gunicorn_access.log" "$LOG_DIR/gunicorn_error.log" "$LOG_DIR/celery.log" "$LOG_DIR/beat.log"
            elif sudo -n true 2>/dev/null; then
                sudo touch "$LOG_DIR/gunicorn_access.log" "$LOG_DIR/gunicorn_error.log" "$LOG_DIR/celery.log" "$LOG_DIR/beat.log"
            fi
        }
        if [ "$EUID" -eq 0 ]; then
            chown -R "$APP_USER":"$APP_USER" "$LOG_DIR" "$PID_DIR"
        elif sudo -n true 2>/dev/null; then
            sudo chown -R "$APP_USER":"$APP_USER" "$LOG_DIR" "$PID_DIR"
        fi
        
        # --- 核心清理逻辑：解决 Beat 自动停止的关键 ---
        rm -f $PROJECT_DIR/celerybeat-schedule
        rm -f $PROJECT_DIR/celerybeat.pid
        rm -f $PID_DIR/*.pid
        find $PROJECT_DIR -name "*.pyc" -delete # 清理字节码防止潜在冲突

        echo -e "${BLUE}>>> 开始启动 workflow-engine 全线服务...${NC}"

        # 1. 启动 Redis
        echo -e "${PURPLE}步骤 1: 检查并启动 Redis...${NC}"
        if pgrep -x redis-server > /dev/null; then
            echo "Redis 已在运行，跳过启动。"
        elif command -v systemctl > /dev/null && sudo -n true 2>/dev/null; then
            sudo systemctl start redis-server || nohup redis-server > $LOG_DIR/redis.log 2>&1 &
        else
            nohup redis-server > $LOG_DIR/redis.log 2>&1 &
        fi
        sleep 1

        # 2. 启动 Gunicorn
        echo -e "${PURPLE}步骤 2: 启动 Gunicorn (Web层)...${NC}"
        run_as_app_user $VENV_PATH/bin/gunicorn $CELERY_APP.wsgi:application \
            --bind 0.0.0.0:$GUNICORN_PORT \
            --workers $GUNICORN_WORKERS \
            --timeout $GUNICORN_TIMEOUT \
            --pid $PID_DIR/gunicorn.pid \
            --access-logfile $LOG_DIR/gunicorn_access.log \
            --error-logfile $LOG_DIR/gunicorn_error.log \
            --daemon

        # 3. 启动 Celery Worker
        echo -e "${PURPLE}步骤 3: 启动 Celery Worker (任务层)...${NC}"
        run_as_app_user nohup $VENV_PATH/bin/celery -A $CELERY_APP worker -l info > $LOG_DIR/celery.log 2>&1 &

        # 4. 启动 Celery Beat
        # 增加 --pidfile 显式指定位置，防止默认位置无写入权限导致停止
        echo -e "${PURPLE}步骤 4: 启动 Celery Beat (调度层)...${NC}"
        run_as_app_user nohup $VENV_PATH/bin/celery -A $CELERY_APP beat \
            --scheduler django_celery_beat.schedulers:DatabaseScheduler \
            --loglevel=INFO \
            --pidfile=$PID_DIR/beat.pid \
            --schedule=$PROJECT_DIR/celerybeat-schedule \
            > $LOG_DIR/beat.log 2>&1 &
        
        sleep 2
        echo -e "${GREEN}>>> 全线启动完成。${NC}"
        "$SCRIPT_PATH" status
        ;;

    stop)
        echo -e "${YELLOW}>>> 正在强制回收所有项目进程...${NC}"
        
        # 停止 Celery (Worker & Beat)
        kill_by_pattern "$APP_USER" "$VENV_PATH/bin/celery -A $CELERY_APP (worker|beat)"
        
        # 停止 Gunicorn
        if [ -f $PID_DIR/gunicorn.pid ]; 
        then
            kill -15 $(cat $PID_DIR/gunicorn.pid) 2>/dev/null
            rm -f $PID_DIR/gunicorn.pid
        fi
        kill_by_pattern "$APP_USER" "$VENV_PATH/bin/gunicorn $CELERY_APP.wsgi:application"

        # 清理残留文件
        rm -f $PROJECT_DIR/celerybeat-schedule
        rm -f $PID_DIR/*.pid
        
        echo -e "${RED}>>> 所有服务已停止并清理。${NC}"
        ;;

    status)
        echo -e "${BLUE}====================================${NC}"
        echo -e "${BLUE}      workflow-engine 项目服务状态           ${NC}"
        echo -e "${BLUE}====================================${NC}"
        check_status "Redis Server" "redis-server"
        check_status "Django (Gunicorn)" "gunicorn $CELERY_APP.wsgi"
        check_status "Celery Worker" "celery -A $CELERY_APP worker"
        check_status "Celery Beat" "celery -A $CELERY_APP beat"
        echo -e "${BLUE}====================================${NC}"
        ;;

    restart)
        "$SCRIPT_PATH" stop
        sleep 3
        "$SCRIPT_PATH" start
        ;;

    monitor)
        if [ ! -x "$MONITOR_SCRIPT" ]; then
            chmod +x "$MONITOR_SCRIPT" 2>/dev/null || true
        fi
        shift
        exec "$MONITOR_SCRIPT" "$@"
        ;;

    *)
        echo "用法: $0 {start|stop|restart|status|monitor [--once|--interval N|--no-heal]}"
        exit 1
        ;;
esac