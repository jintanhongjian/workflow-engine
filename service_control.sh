#!/bin/bash

# --- 基础配置 ---
PROJECT_DIR="/django-website/LMI_OA"
VENV_PATH="$PROJECT_DIR/.venv"
LOG_DIR="$PROJECT_DIR/logs"
PID_DIR="$PROJECT_DIR/pids"
CELERY_APP="LMI_OA"

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
        
        # --- 核心清理逻辑：解决 Beat 自动停止的关键 ---
        rm -f $PROJECT_DIR/celerybeat-schedule
        rm -f $PROJECT_DIR/celerybeat.pid
        rm -f $PID_DIR/*.pid
        find $PROJECT_DIR -name "*.pyc" -delete # 清理字节码防止潜在冲突

        echo -e "${BLUE}>>> 开始启动 LMI_OA 全线服务...${NC}"

        # 1. 启动 Redis
        echo -e "${PURPLE}步骤 1: 检查并启动 Redis...${NC}"
        sudo systemctl start redis-server || nohup redis-server > $LOG_DIR/redis.log 2>&1 &
        sleep 1

        # 2. 启动 Gunicorn
        echo -e "${PURPLE}步骤 2: 启动 Gunicorn (Web层)...${NC}"
        $VENV_PATH/bin/gunicorn $CELERY_APP.wsgi:application \
            --bind 0.0.0.0:$GUNICORN_PORT \
            --workers $GUNICORN_WORKERS \
            --timeout $GUNICORN_TIMEOUT \
            --pid $PID_DIR/gunicorn.pid \
            --access-logfile $LOG_DIR/gunicorn_access.log \
            --error-logfile $LOG_DIR/gunicorn_error.log \
            --daemon

        # 3. 启动 Celery Worker
        echo -e "${PURPLE}步骤 3: 启动 Celery Worker (任务层)...${NC}"
        nohup sudo -u jintanhongjian $VENV_PATH/bin/celery -A $CELERY_APP worker -l info > $LOG_DIR/celery.log 2>&1 &
        echo $! > $PID_DIR/worker.pid

        # 4. 启动 Celery Beat
        # 增加 --pidfile 显式指定位置，防止默认位置无写入权限导致停止
        echo -e "${PURPLE}步骤 4: 启动 Celery Beat (调度层)...${NC}"
        nohup $VENV_PATH/bin/celery -A $CELERY_APP beat \
            --scheduler django_celery_beat.schedulers:DatabaseScheduler \
            --loglevel=INFO \
            --pidfile=$PID_DIR/beat.pid \
            --schedule=$PROJECT_DIR/celerybeat-schedule \
            > $LOG_DIR/beat.log 2>&1 &
        
        sleep 2
        echo -e "${GREEN}>>> 全线启动完成。${NC}"
        $0 status
        ;;

    stop)
        echo -e "${YELLOW}>>> 正在强制回收所有项目进程...${NC}"
        
        # 停止 Celery (Worker & Beat)
        pkill -9 -f "celery -A $CELERY_APP"
        
        # 停止 Gunicorn
        if [ -f $PID_DIR/gunicorn.pid ]; then
            kill -15 $(cat $PID_DIR/gunicorn.pid) 2>/dev/null
            rm -f $PID_DIR/gunicorn.pid
        fi
        pkill -9 -f "gunicorn $CELERY_APP.wsgi"

        # 清理残留文件
        rm -f $PROJECT_DIR/celerybeat-schedule
        rm -f $PID_DIR/*.pid
        
        echo -e "${RED}>>> 所有服务已停止并清理。${NC}"
        ;;

    status)
        echo -e "${BLUE}====================================${NC}"
        echo -e "${BLUE}      LMI_OA 项目服务状态           ${NC}"
        echo -e "${BLUE}====================================${NC}"
        check_status "Redis Server" "redis-server"
        check_status "Django (Gunicorn)" "gunicorn $CELERY_APP.wsgi"
        check_status "Celery Worker" "celery -A $CELERY_APP worker"
        check_status "Celery Beat" "celery -A $CELERY_APP beat"
        echo -e "${BLUE}====================================${NC}"
        ;;

    restart)
        $0 stop
        sleep 3
        $0 start
        ;;

    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac