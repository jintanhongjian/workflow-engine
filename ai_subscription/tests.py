from django.test import TestCase
from .tasks import dispatch_periodic_reports
from unittest.mock import patch

class TaskTest(TestCase):
    def test_dispatch_logic(self):
        # 方案 A：如果你只想测试逻辑，不想真的连 Redis
        # 使用 patch 拦截 delay，防止它真的去连接网络
        with patch('ai_subscription.tasks.dispatch_periodic_reports.delay') as mock_task:
            # 现在调用不会报错了，因为它被“拦截”了
            dispatch_periodic_reports.delay()
            self.assertTrue(mock_task.called)

    def test_run_immediately(self):
        # 方案 B：如果你真的想连 Redis 测试
        # 那么你必须先在后台启动 sudo systemctl start redis-server
        # 然后调用同步版本 .apply() 而不是 .delay()，这样它会在当前进程运行
        result = dispatch_periodic_reports.apply()
        self.assertTrue(result.successful())