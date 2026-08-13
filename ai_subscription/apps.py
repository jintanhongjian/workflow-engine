from django.apps import AppConfig

class AiSubscriptionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai_subscription'
    # 添加这一行
    verbose_name = 'AI 订阅管理系统'
    def ready(self):
        # 核心：当 Django 准备好后，导入信号量
        import ai_subscription.signals
