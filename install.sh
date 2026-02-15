#!/bin/bash

# 报错即停止
set -e

echo "🚀 开始安装项目环境..."

# 1. 更新系统并安装系统级依赖
echo "📦 更新系统软件包..."
sudo apt-get update
sudo apt-get install -y \
    python3.12-dev \
    build-essential \
    libpq-dev \
    redis-server \
    curl \
    git

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

echo "✅ 安装完成！"
echo "💡 请运行 'source .venv/bin/activate' 激活环境，然后运行 './service_control.sh start' 启动服务。"