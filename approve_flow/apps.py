from django.apps import AppConfig


class ApproveFlowConfig(AppConfig):
    name = 'approve_flow'
    verbose_name = '审批流程管理'
    def ready(self):
        # 核心：当 Django 准备好后，导入信号量
        import approve_flow.signals
        from django.contrib import admin
        admin.site.site_header = "审批流引擎 - Workflow Engine"    
