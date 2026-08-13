from django.db import models
import os
import json
from datetime import datetime
from django.utils import timezone
from django.conf import settings


def get_subscription_upload_path(instance, filename):
    """
    确定文件上传的物理路径
    instance: 当前 ReferenceDocument 的实例
    filename: 原始文件名
    """
    # 获取关联的订阅对象
    subscription = instance.subscription
    
    # 资深程序员的避坑处理：
    # 如果是新创建的订阅，id 可能还没产生，此时建议使用临时的 uuid 或用户名
    # 但由于我们通常是先有 Subscription 实例再有附件，所以通常能拿到 id
    sub_id = subscription.id if subscription.id else "temp_upload"
    
    # 构造路径：media/ai_reports/sub_42/your_file.pdf
    return os.path.join('reference_docs', f'sub_{sub_id}', filename)

# ... 这里是你之前的 Subscription 和 ReferenceDocument 模型 ...
class Subscription(models.Model):
    # 创建者隔离：每个任务属于一个 Django User
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='owned_subscriptions'
    )
    
    # 订阅人信息
    user_name = models.CharField(max_length=100, verbose_name="订阅人姓名")
    user_email = models.EmailField(verbose_name="接收邮箱")
    
    # 将简报名称设为唯一索引
    report_title = models.CharField(
        max_length=200, 
        unique=True, 
        verbose_name="简报名称",
        error_messages={
            'unique': "该简报名称已存在，请换一个名字。"
        }
    )
    
    # 核心逻辑
    keywords = models.CharField(max_length=500, verbose_name="关注关键词")
    description = models.TextField(blank=False, verbose_name="详细内容描述",        
                                   error_messages={
                                        'required': "该简报名称已存在，请换一个名字。"
                                    })
    
    # 交付设置
    PERIOD_CHOICES = [
        ('daily', '每日汇总'),
        ('weekly', '每周复盘'),
        ('monthly', '每月总结'),
        ('quarterly', '季度深挖'),
        ('yearly', '年度汇报'),
        ('realtime', '实时推送'),
    ]
    period = models.CharField(max_length=20, choices=PERIOD_CHOICES, default='daily', verbose_name="生成周期")
    send_time = models.TimeField(verbose_name="推送时间", default="09:00")
    format_type = models.CharField(max_length=50, verbose_name="输出格式模板")
    
    subscription_date = models.DateField(
        default=timezone.now, 
        verbose_name="订阅日期",
        help_text="您可以手动调整此订阅的起始日期"
    )
    is_active = models.BooleanField(default=True, verbose_name="是否激活")
    last_run_at = models.DateTimeField(null=True, blank=True, verbose_name="上次运行时间")


    # 元数据
    class Meta:
        ordering = ['-subscription_date']  # 默认按订阅日期倒序排列
        verbose_name = "subscription"
        verbose_name_plural = "AI subscriptions"

    def __str__(self):
        return f"{self.report_title} - {self.user_name}"

class SubscriptionRecipient(models.Model):
    # 关联订阅任务
    subscription = models.ForeignKey(
        Subscription, 
        on_delete=models.CASCADE, 
        related_name='recipient_list'
    )
    # 接收人邮箱
    email = models.EmailField(verbose_name="接收人邮箱")
    recipient_name = models.CharField(max_length=100, blank=True, verbose_name="接收人姓名")
    class Meta:
        # 同一订阅下防止重复添加相同邮箱
        unique_together = ('subscription', 'email')
        verbose_name = "subscription recipient"
        verbose_name_plural = "subscription recipients"
        
    def __str__(self):
        return f"{self.email} -> {self.subscription.report_title}"

class ReferenceDocument(models.Model):
    # 关联订阅任务：当订阅删除时，文件记录也随之删除
    subscription = models.ForeignKey(
        Subscription, 
        related_name='documents', 
        on_delete=models.CASCADE
    )
    upload_path = get_subscription_upload_path # 存储路径：media/ai_docs/<ID>/
    file = models.FileField(upload_to=upload_path, verbose_name="参考文档")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    
    # 元数据
    class Meta:
        ordering = ['-uploaded_at']  # 默认按上传时间倒序排列
        verbose_name = "reference document"
        verbose_name_plural = "reference documents"
    
    def __str__(self):
        return self.file.name

class ReportHistory(models.Model):
    # 关联订阅 ID，当订阅删除时，历史记录通常建议保留 (on_delete=models.SET_NULL) 
    # 或者跟随删除 (on_delete=models.CASCADE)
    subscription = models.ForeignKey(
        Subscription, 
        on_delete=models.CASCADE, 
        related_name='histories',
        verbose_name="所属订阅"
    )
    
    report_date = models.DateTimeField(auto_now_add=True, verbose_name="简报生成时间")
    
    # 接收人邮件，存储为： "aaa@test.com, bbb@test.com"
    recipients = models.TextField(verbose_name="接收人列表")
    
    # 简报内容，使用 TextField 存储完整的内容
    content_markdown = models.TextField(verbose_name="简报格式文本")
    
    # 摘要，用于在列表中预览
    summary = models.CharField(max_length=255, blank=True, verbose_name="内容摘要")

    class Meta:
        ordering = ['-report_date'] # 默认按时间倒序排列
        verbose_name = "report history"
        verbose_name_plural = "report histories"

    def __str__(self):
        return f"{self.subscription.report_title} - {self.report_date.strftime('%Y-%m-%d')}"


class TaskLog(models.Model):
    task_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20) # SUCCESS, FAILURE
    error_message = models.TextField(null=True, blank=True)
    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-executed_at']    