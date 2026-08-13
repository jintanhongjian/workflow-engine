
from django.apps import AppConfig
from django.conf import settings
import pytz

# 项目的API接口和用户验证服务   
class ApiServicesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api_services'
    verbose_name = "API Services"   # 在 Django 管理后台显示的名称
    
    # --- 强制修复 Django 6.0 + Celery Beat 兼容性补丁 ---
    @classmethod
    def patch_celery_beat(cls):
        try:
            import django_celery_beat.models as beat_models
            # Django/Celery-Beat 需要时区对象（具有 .zone），不能返回纯字符串
            def _patched_celery_timezone():
                tz_name = getattr(settings, 'CELERY_TIMEZONE', None) or getattr(settings, 'TIME_ZONE', 'Asia/Shanghai')
                return pytz.timezone(tz_name)

            beat_models.crontab_schedule_celery_timezone = _patched_celery_timezone
        except (ImportError, AttributeError):
            pass
        except Exception as e:
            print(f">>> 补丁注入失败: {e}")

    def ready(self):
        # 核心：当 Django 准备好后，导入信号量
        import api_services.signals
        # --- 补丁结束 ---     
        self.patch_celery_beat()