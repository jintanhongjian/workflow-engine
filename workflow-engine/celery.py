import os
from celery import Celery

# 设置 Django 默认配置模块
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'workflow-engine.settings')

app = Celery('workflow-engine')

# 使用 Redis 作为消息中间件 (Broker)
app.config_from_object('django.conf:settings', namespace='CELERY')

# 自动发现所有 app 下的 tasks.py
app.autodiscover_tasks()