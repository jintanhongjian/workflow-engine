import os
import sys
import socket
import django
from django.conf import settings

# 1. 颜色配置
class Colors:
    OK = '\033[92m[PASS] '
    FAIL = '\033[91m[FAIL] '
    WARN = '\033[93m[WARN] '
    END = '\033[0m'

def check_port(host, port, service_name):
    """检查物理端口是否连通"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(2)
        try:
            s.connect((host, port))
            print(f"{Colors.OK}{service_name} 端口 {port} 响应正常")
            return True
        except Exception:
            print(f"{Colors.FAIL}{service_name} 端口 {port} 无法连接！(Errno 111)")
            return False

def init_django():
    """初始化 Django 环境"""
    try:
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'LMI_OA.settings')
        django.setup()
        print(f"{Colors.OK}Django 环境初始化成功")
        return True
    except Exception as e:
        print(f"{Colors.FAIL}Django 环境初始化失败: {e}")
        return False

def check_redis_celery():
    """检查 Celery 代理配置"""
    try:
        from celery import Celery
        app = Celery('LMI_OA')
        app.config_from_object('django.conf:settings', namespace='CELERY')
        
        # 测试 Broker 连接
        with app.connection().ensure_connection(max_retries=1) as conn:
            print(f"{Colors.OK}Celery 成功连接到 Broker: {conn.as_uri()}")
            return True
    except Exception as e:
        print(f"{Colors.FAIL}Celery 无法连接到 Broker！请检查 settings.py 和 Redis 状态。")
        print(f"      错误详情: {e}")
        return False

def check_db_fields():
    """检查关键字段是否存在（防止 AttributeError）"""
    try:
        from ai_subscription.models import Subscription
        fields = [f.name for f in Subscription._meta.get_fields()]
        required = ['is_active', 'last_run_at']
        
        missing = [f for f in required if f not in fields]
        if not missing:
            print(f"{Colors.OK}数据库模型字段检查通过 (包含: {', '.join(required)})")
            return True
        else:
            print(f"{Colors.FAIL}数据库缺少关键字段: {missing}。请运行 makemigrations 和 migrate！")
            return False
    except Exception as e:
        print(f"{Colors.FAIL}数据库模型访问失败: {e}")
        return False

if __name__ == "__main__":
    print("="*40)
    print("      LMI-OA 项目依赖深度检查")
    print("="*40)

    # 步骤 1: 物理端口检查
    r_ok = check_port('127.0.0.1', 6379, 'Redis')
    
    # 步骤 2: Django 基础环境
    d_ok = init_django()
    
    f_ok=False
    c_ok=False
    
    if d_ok:
        # 步骤 3: 数据库结构检查
        f_ok = check_db_fields()
        # 步骤 4: Celery 通路检查
        c_ok = check_redis_celery()
    
    print("="*40)
    if all([r_ok, d_ok, f_ok, c_ok]):
        print(f"{Colors.OK}所有服务就绪，可以安全运行程序。")
        sys.exit(0) # 成功退出码
    else:
        print(f"{Colors.FAIL}项目环境存在隐患，请根据上方红字修复。")
        sys.exit(1) # 失败退出码
    print("="*40)
        