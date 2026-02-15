#!/bin/bash

# --- 配置 ---
DB_PATH="/django-website/LMI_OA/db.sqlite3"
BACKUP_DIR="/django-website/LMI_OA/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/db_backup_$DATE.sqlite3"

# --- 执行备份 ---
# 使用 sqlite3 官方备份命令，确保数据一致性
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

# --- 保持整洁 ---
# 只保留最近 30 天的备份，防止硬盘被撑爆
find "$BACKUP_DIR" -type f -name "*.sqlite3" -mtime +30 -delete

echo "备份完成: $BACKUP_FILE"