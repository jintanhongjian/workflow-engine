#!/bin/bash

# --- 配置与路径 ---
PROJECT_DIR="/django-website/LMI_OA"
CONTROL_SCRIPT="$PROJECT_DIR/service_control.sh"
LOG_FILE="$PROJECT_DIR/logs/monitor.log"

# 切换到项目目录
cd $PROJECT_DIR

# 获取当前时间
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

# --- 检查函数 ---
# 检查进程是否存在，如果不存在则调用控制脚本启动
check_and_restart() {
    local label=$1
    local search_str=$2
    
    if ! ps aux | grep "$search_str" | grep -v grep > /dev/null; then
        echo "[$TIMESTAMP] 警告: $label 已停止，正在尝试重启..." >> $LOG_FILE
        # 调用你之前的控制脚本启动服务
        # 注意：这里我们只调用 start，你的 start 脚本里已经包含了清理 pid 的逻辑
        $CONTROL_SCRIPT start >> $LOG_FILE 2>&1
        echo "[$TIMESTAMP] $label 重启指令已发送。" >> $LOG_FILE
    fi
}

# --- 执行监控 ---
# 重点监控 Celery Beat (最容易挂)
check_and_restart "Celery Beat" "celery -A LMI_OA beat"

# (可选) 也可以顺便监控 Worker 或 Gunicorn
check_and_restart "Celery Worker" "celery -A LMI_OA worker"
check_and_restart "Gunicorn" "gunicorn LMI_OA.wsgi"
find /django-website/LMI_OA/logs/ -name "*.log" -mtime +7 -exec rm -f {} \;