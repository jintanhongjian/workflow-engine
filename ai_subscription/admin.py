from django.contrib import admin
from .models import Subscription, ReferenceDocument
from .models import ReportHistory, SubscriptionRecipient,TaskLog 
from django.utils.safestring import mark_safe

# --- 新增：定义接收人的内联管理 ---
class SubscriptionRecipientInline(admin.TabularInline):
    model = SubscriptionRecipient
    extra = 1  # 默认显示一个空行供后台手动添加邮箱
    fields = ('email',)

# 1. 定义参考文档的内联管理
class ReferenceDocumentInline(admin.TabularInline):
    model = ReferenceDocument
    extra = 0
    readonly_fields = ('uploaded_at',)
    fields = ('file', 'uploaded_at')

# 2. 修改：定义订阅任务的管理后台
@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    # 【替换】列表页显示的字段：移除 user_name/email，加入 creator 和接收人总数
    list_display = ('report_title', 'creator', 'recipient_count', 'period', 'send_time', 'subscription_date', 'is_active')
    
    # 【修改】右侧过滤器：加入按创建者筛选
    list_filter = ('period', 'format_type', 'subscription_date', 'creator', 'is_active')
    
    # 【修改】搜索框配置：移除 user_name/email，加入 creator 搜索
    search_fields = ('creator__username', 'report_title', 'keywords', 'description')
    
    # 【替换】详情页分组布局
    fieldsets = (
        ('基础信息', {
            'fields': ('creator',) # 替换了原来的 user_name, user_email
        }),
        ('简报配置', {
            'fields': ('report_title', 'keywords', 'description')
        }),
        ('推送设置', {
            'fields': ('period', 'send_time', 'format_type')
        }),
        ('订阅时间管理', {
            'fields': ('subscription_date', 'is_active')
        }),
    )
    
    # 【修改】将接收人和参考文档同时内联到详情页
    inlines = [SubscriptionRecipientInline, ReferenceDocumentInline]

    # --- 新增：自定义展示逻辑 ---
    def recipient_count(self, obj):
        """计算该订阅下的接收人总数"""
        return obj.recipient_list.count()
    recipient_count.short_description = '接收人总数'

# 3. 报告历史管理保持不变
@admin.register(ReportHistory)
class ReportHistoryAdmin(admin.ModelAdmin):
    list_display = ('subscription', 'report_date', 'short_recipients', 'short_content')
    list_filter = ('subscription', 'report_date')
    search_fields = ('recipients', 'content_markdown', 'subscription__report_title')
    
    def short_recipients(self, obj):
        return obj.recipients[:30] + '...' if len(obj.recipients) > 30 else obj.recipients
    short_recipients.short_description = '接收人'

    def short_content(self, obj):
        return obj.content_markdown[:50] + '...' if obj.content_markdown else "无内容"
    short_content.short_description = '简报摘要'

    readonly_fields = ('report_date', 'markdown_preview')
    fields = ('subscription', 'recipients', 'content_markdown', 'markdown_preview', 'report_date')
    
    def markdown_preview(self, obj):
        return mark_safe(f'<div style="background:#f9f9f9; padding:10px; border:1px solid #ddd;">{obj.content_markdown[:500]}...</div>')
    markdown_preview.short_description = '内容实时预览'

@admin.register(TaskLog)
class TaskLogAdmin(admin.ModelAdmin):
    # 将 list_display 中的 created_at 改为 executed_at
    list_display = ('task_name', 'colored_status', 'executed_at', 'error_message_summary')
    
    # 将 list_filter 中的 created_at 改为 executed_at
    list_filter = ('status', 'executed_at')
    
    # 将 readonly_fields 中的 created_at 改为 executed_at
    readonly_fields = ('task_name', 'status', 'error_message', 'executed_at')

    def colored_status(self, obj):
        from django.utils.html import format_html
        # 根据你的 status 存储内容（成功/失败 或 SUCCESS/FAILURE）进行匹配
        color = 'green' if obj.status in ['成功', 'SUCCESS'] else 'red'
        if obj.status in ['重试中', 'RETRY']: color = 'orange'
        return format_html('<b style="color:{};">{}</b>', color, obj.status)
    colored_status.short_description = "状态"

    def error_message_summary(self, obj):
        if obj.error_message:
            return obj.error_message[:100] + '...' if len(obj.error_message) > 100 else obj.error_message
        return "-"
    error_message_summary.short_description = "详情/错误"

# 注册其他模型
admin.site.register(ReferenceDocument)
admin.site.register(SubscriptionRecipient) # 建议也将接收人模型注册，方便全局搜索邮箱