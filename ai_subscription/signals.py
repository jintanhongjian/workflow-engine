from django.dispatch import receiver
from django.conf import settings
from django.db.models.signals import post_save, post_delete
from django_celery_beat.models import PeriodicTask, CrontabSchedule
from kombu.exceptions import OperationalError  # 导入异常类
from .tasks import send_bulk_email_task, task_generate_ai_report # 导入定义的任务
from .models import Subscription, ReferenceDocument, ReportHistory, SubscriptionRecipient
import os,json
import shutil

# 当 ReferenceDocument 的实例被删除后，自动触发此函数
@receiver(post_delete, sender=ReferenceDocument)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    if instance.file:
        # 资深程序员准则：永远不要假设文件一定存在
        if os.path.isfile(instance.file.path):
            try:
                os.remove(instance.file.path)
            except Exception as e:
                print(f"文件删除失败: {e}") # 记录错误但不崩溃

# (可选) 如果你希望删除整个订阅时，清理整个文件夹，可以添加这个：
@receiver(post_delete, sender=Subscription)
def auto_delete_dir_on_delete(sender, instance, **kwargs):
    """
    当订阅记录被删除时，彻底清理该订阅对应的整个物理文件夹
    """
    # 构造文件夹的绝对路径
    # 路径示例: /your/project/media/reference_docs/sub_42
    folder_path = os.path.join(settings.MEDIA_ROOT, 'reference_docs', f'sub_{instance.id}')
    if os.path.exists(folder_path):
        try:
            # 使用 shutil.rmtree 递归删除文件夹及其内部所有内容
            shutil.rmtree(folder_path)
            print(f"DEBUG: 成功清理订阅 ID 为 {instance.id} 的专属目录")
        except Exception as e:
            # 记录异常，防止因权限或文件占用导致 500 错误
            print(f"ERROR: 文件夹清理失败 - {e}")

@receiver(post_save, sender=Subscription)
def setup_periodic_report(sender, instance, created, **kwargs):
    """
    当订阅保存时，自动创建或更新 Celery 定时任务
    """
    if instance.period == 'realtime':
        try:
            # 1. 立即运行模式：直接丢进 Celery 任务队列
            # 这样做用户点击“保存”后，后台会立即开始调用 Gemini
            print(f"立即运行：直接丢进 Celery 任务队列,开始调用 Gemini生成报告。")
            task_generate_ai_report.delay(instance.id)
            # 2. 清理工作：如果该订阅之前是“每日”，现在改成了“实时”，
            # 我们需要删除之前的定时任务，防止重复触发
            PeriodicTask.objects.filter(name=f"Generate Report: {instance.id}").delete()
        except (OperationalError, Exception) as e:
            # 即使 Redis 挂了，也要让用户能保存成功
            print(f"警告：Celery 任务分发失败，Redis 可能未启动: {e}")
            # 这里可以选择同步运行（慎用，会卡死网页）或者干脆记录日志等下次调度
        return    
    # 定义时间表 (假设根据 instance.send_time 获取小时和分钟)
    send_time = instance.send_time
    # 如果 send_time 是字符串，将其转换为 time 对象
    if isinstance(send_time, str):
        try:
            # 假设你的时间格式是 "HH:MM"，例如 "09:30"
            send_time_obj = datetime.strptime(send_time, "%H:%M").time()
        except ValueError:
            # 处理可能的格式错误（例如 "09:30:00"）
            send_time_obj = datetime.strptime(send_time, "%H:%M:%S").time()
    else:
        send_time_obj = send_time    
    hour = send_time_obj.hour
    minute = send_time_obj.minute
    
    report_date=instance.subscription_date
    dom = report_date.day
    dow=report_date.isoweekday()
    report_month = report_date.month
    # 根据 period 字段设置不同的 Crontab
    if instance.period == 'daily':
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute=minute, hour=hour, day_of_week='*', day_of_month='*', month_of_year='*',
            # ！！！关键：显式指定字符串，不要让它去查字段的默认 CHOICES
            timezone='Asia/Shanghai'
        )
    elif instance.period == 'weekly':
        # 假设每周一发送
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute=minute, hour=hour, day_of_week=dow, day_of_month='*', month_of_year='*',
            # ！！！关键：显式指定字符串，不要让它去查字段的默认 CHOICES
            timezone='Asia/Shanghai'            
        )
    elif instance.period == 'monthly':
        # 每月 1 号发送
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute=minute, hour=hour, day_of_week='*', day_of_month=dom, month_of_year='*',
            # ！！！关键：显式指定字符串，不要让它去查字段的默认 CHOICES
            timezone='Asia/Shanghai'            
        )
    elif instance.period == 'quarterly':
        # 每季度（1, 4, 7, 10月）的 1 号发送
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute=minute, hour=hour, day_of_week='*', day_of_month=dom, month_of_year='1,4,7,10',
            # ！！！关键：显式指定字符串，不要让它去查字段的默认 CHOICES
            timezone='Asia/Shanghai'            
        )
    elif instance.period == 'yearly':
        # 每年 1 月 1 号发送
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute=minute, hour=hour, day_of_week='*', day_of_month=dom, month_of_year='1',
            # ！！！关键：显式指定字符串，不要让它去查字段的默认 CHOICES
            timezone='Asia/Shanghai'            
        )

    # 准备周期名称映射，增强可读性
    period_map = {
        'realtime': '实时推送',
        'daily': '每日推送',
        'weekly': '每周推送',
        'monthly': '每月推送',
        'quarterly': '每季度推送',
        'yearly': '每年推送',
    }

    # 拼接详细的任务描述
    # 包含：报告标题 + 周期类型 + 具体的推送时间/日期
    friendly_period = period_map.get(instance.period, instance.period)
    task_desc = (
        f"报告名称: {instance.report_title} | "
        f"运行周期: {friendly_period} ({schedule.human_readable if hasattr(schedule, 'human_readable') else str(schedule)})| "
        f"计划时间: {instance.send_time.strftime('%H:%M')} | "
        f"订阅日期: {instance.subscription_date}"
    
    )

    # 创建或更新定时任务
    task_name = f"Generate Report: {instance.id}"
    PeriodicTask.objects.update_or_create(
        name=task_name,
        defaults={
            'crontab': schedule,
            # 必须显式设为 None，防止 ValidationError
            'interval': None,        
            'solar': None,
            'clocked': None,
            'task': 'workflow-engine.tasks.task_generate_ai_report', # 执行你的异步生成函数
            'args': json.dumps([instance.id]), # 传递参数
            'enabled': instance.is_active,
            'description': task_desc
        }
    )

@receiver(post_delete, sender=Subscription)
def delete_periodic_report(sender, instance, **kwargs):
    """当订阅删除时，同步删除定时任务"""
    PeriodicTask.objects.filter(name=f"Generate Report: {instance.id}").delete()

@receiver(post_save, sender=ReportHistory)
def auto_send_email_after_save(sender, instance, created, **kwargs):
    """
    当 ReportHistory 实例被创建并保存后，自动触发邮件发送给所有接收人
    """
    if created:  # 确保只在新建记录时发送
        subscription = instance.subscription
        
        # 1. 检查订阅是否处于激活状态
        if not subscription.is_active:
            print(f"订阅 {subscription.report_title} 已停用，跳过发送。")
            return

        # 2. 获取当前这一刻的接收人邮箱列表
        # 使用 values_list 拿到 ['a@b.com', 'c@d.com']
        recipient_emails = list(subscription.recipient_list.values_list('email', flat=True))
        # print(f"准备发送订阅 {subscription.report_title} 给以下接收人: {recipient_emails}")
        if not recipient_emails:
            print(f"警告：订阅 {subscription.report_title} 没有配置任何接收人。")
            return

        # 3. 将邮箱列表转为逗号分隔的字符串，保存到 instance.recipients
        # 这样即便以后订阅成员删除了，这条历史记录里依然存着“当时发给谁了”
        instance.recipients = ", ".join(recipient_emails)
        # print(f"保存订阅 {subscription.report_title} 的接收人列表到历史记录: {instance.recipients}")
        # 使用 update 专门更新 recipients 字段，避免触发另一个 post_save 导致死循环
        sender.objects.filter(id=instance.id).update(recipients=instance.recipients)

        # 4. 【生产级改进】：将发送任务推送到 Celery 队列
        # 传递 list 类型以确保能够被序列化
        send_bulk_email_task.delay(
            recipient_emails=recipient_emails,
            report_title=subscription.report_title,
            md_content=instance.content_markdown
        )
