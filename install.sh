#!/bin/bash

# 报错即停止
set -e

echo "🚀 开始安装项目环境..."

# 1. 更新系统并安装系统级依赖
echo "📦 更新系统软件包..."

# Ensure Node.js 20 is available
sudo apt-get update
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -

sudo apt-get install -y \
    python3.12-dev \
    build-essential \
    libpq-dev \
    redis-server \
    curl \
    git \
    nodejs \
    npm \
    sqlite3 \
    redis-tools \
    gettext

# 2. 安装 postgresql (如果尚未安装)
set -e
if command -v apt >/dev/null 2>&1; then
  sudo apt update && sudo apt install -y postgresql postgresql-contrib
elif command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y postgresql-server postgresql-contrib
elif command -v yum >/dev/null 2>&1; then
  sudo yum install -y postgresql-server postgresql-contrib
else
  echo "No supported package manager found (apt/dnf/yum)." >&2
  exit 1
fi

sudo npm install -g @github/copilot
sudo npm install -g @google/gemini-cli@latest

# 2. 安装 uv (如果尚未安装)
if ! command -v uv &> /dev/null; then
    echo "🛠️ 安装 uv 包管理器..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.cargo/env
fi

# 3. 启动并配置 Redis
echo "🔄 启动 Redis 服务..."
sudo service redis-server start

# 4. 创建虚拟环境
echo "🐍 创建虚拟环境 (.venv)..."
if [ -d ".venv" ]; then
    rm -rf .venv
fi
uv venv --python 3.12

# 激活虚拟环境
source .venv/bin/activate

# 5. 安装 Python 依赖
echo "📥 安装 requirements.txt 中的依赖..."
uv pip install -r requirements.txt

# 6. 执行 Django 数据库迁移
echo "🗄️ 执行数据库迁移..."
python manage.py migrate

# 7. 收集静态文件
echo "🎨 收集静态文件..."
python manage.py collectstatic --noinput

# 8. 配置 PostgreSQL 业务库环境变量（当前会话 + 持久化）
echo "🔐 配置 PostgreSQL 业务库环境变量..."
export BUSINESS_DB_NAME="workflow_business"
export BUSINESS_DB_USER="workflow_user"
export BUSINESS_DB_PASSWORD="workflow_pass"
export BUSINESS_DB_HOST="127.0.0.1"
export BUSINESS_DB_PORT="5432"
# 模型选择策略（可选: general / coding / fast）
export MODEL_SELECT_PURPOSE="${MODEL_SELECT_PURPOSE:-general}"

ENV_FILE="$HOME/.workflow_engine_env"
cat > "$ENV_FILE" <<'EOF'
export BUSINESS_DB_NAME="workflow_business"
export BUSINESS_DB_USER="workflow_user"
export BUSINESS_DB_PASSWORD="workflow_pass"
export BUSINESS_DB_HOST="127.0.0.1"
export BUSINESS_DB_PORT="5432"
# 模型选择策略（可选值三选一）
export MODEL_SELECT_PURPOSE="general"  # 默认
# export MODEL_SELECT_PURPOSE="coding"
# export MODEL_SELECT_PURPOSE="fast"
EOF

if ! grep -q 'source "$HOME/.workflow_engine_env"' "$HOME/.bashrc"; then
  echo 'source "$HOME/.workflow_engine_env"' >> "$HOME/.bashrc"
fi

echo "✅ 安装完成！"
echo "💡 请运行 'source .venv/bin/activate' 激活环境，然后运行 './service_control.sh start' 启动服务。"