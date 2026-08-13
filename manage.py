#!/usr/bin/env python3
"""Django's command-line utility for administrative tasks."""
import os
import sys

def main():
    # 关键：允许在非 HTTPS 环境下运行（本地回调通常是 http://localhost）
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    # 关键：忽略 state 校验错误
    os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'    
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'workflow-engine.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
    # from django_celery_beat.models import PeriodicTask
    # for task in PeriodicTask.objects.all():
    #     print(f"任务: {task.name} | 规则: {task.crontab}")