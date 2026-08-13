from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .services import generate_report_with_attachments, generate_subscription_report
from .models import Subscription, TaskLog
from celery.signals import task_postrun
from django.db import transaction
from django.contrib import messages
from api_services.google_service import send_markdown_report
import logging


logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def task_generate_ai_report(self, sub_id):
    """
    异步执行 Gemini 报告生成任务
    """
    try:
        subscription = Subscription.objects.get(id=sub_id)
        # 调用之前写的 services 逻辑
        report = generate_report_with_attachments(subscription)
        # print(report.content_markdown)
        if report:
            return f"Report {report.id} generated successfully."
    except Exception as e:
        # 使用 self.retry 进行重试
        raise self.retry(exc=e, countdown=60)
    
@shared_task(bind=True, max_retries=3)
def dispatch_periodic_reports(self):
    """
    智能调度程序：扫描所有手动配置或需要检查的订阅任务
    """
    now = timezone.now()
    # 只处理激活状态的订阅
    subscriptions = Subscription.objects.filter(is_active=True) 
    
    dispatch_count = 0
    
    for sub in subscriptions:
        # 跳过实时推送模式，因为实时模式由信号(Signal)立即触发
        if sub.period == 'realtime':
            continue
            
        should_run = False
        last_run = sub.last_run_at

        # 1. 核心判断逻辑：兼容季度和年度
        if not last_run:
            should_run = True
        else:
            if sub.period == 'daily' and now >= last_run + timedelta(days=1):
                should_run = True
            elif sub.period == 'weekly' and now >= last_run + timedelta(weeks=1):
                should_run = True
            elif sub.period == 'monthly' and now >= last_run + timedelta(days=30):
                should_run = True
            elif sub.period == 'quarterly' and now >= last_run + timedelta(days=90):
                should_run = True
            elif sub.period == 'yearly' and now >= last_run + timedelta(days=365):
                should_run = True

        # 2. 触发任务
        if should_run:
            # 使用原子操作更新时间，防止并发重复触发
            with transaction.atomic():
                sub.last_run_at = now
                sub.save()
            
            # 关键：不要在这里同步运行 AI 逻辑，而是丢入队列实现“任务打散”
            # 这样即便有 1000 个订阅到期，也不会卡死调度进程
            task_generate_ai_report.delay(sub.id)
            # task_generate_ai_report(sub.id) # 去掉 .delay，直接运行函数
            dispatch_count += 1
            print(f"🚀 [调度中心] 已分发任务: {sub.report_title} ({sub.period})")

    return f"调度完成，本次共触发 {dispatch_count} 个任务。"
            
@shared_task(bind=True, max_retries=3)
def send_bulk_email_task(self, recipient_emails, report_title, md_content):
    """
    异步批量发送邮件任务
    """
    success_count = 0
    fail_count = 0
    
    for email in recipient_emails:
        try:
            send_markdown_report(
                to_email=email,
                report_title=report_title,
                md_content=md_content
            )
            success_count += 1
        except Exception as exc:
            logger.error(f"发送至 {email} 失败: {exc}")
            fail_count += 1
            # 抛出重试异常，countdown=60 表示 60 秒后重试
            raise self.retry(exc=exc, countdown=60)
    return f"发送完成: 成功 {success_count}, 失败 {fail_count}"   

@task_postrun.connect(sender='ai_subscription.tasks.send_bulk_email_task')
def log_task_result(task_id, retval, state, args, kwargs, **others):
    """
    任务运行结束后自动记录状态，并关联订阅任务
    """
    # 从 kwargs 中提取订阅信息（我们在调用 delay 时传的参数）
    # 如果你是按位置传参，则从 args[0] 获取
    report_title = kwargs.get('report_title') or (args[1] if len(args) > 1 else "未知报告")
    
    status_mapping = {
        'SUCCESS': '成功',
        'FAILURE': '失败',
        'RETRY': '重试中',
        'REVOKED': '已取消'
    }

    # 创建日志记录
    TaskLog.objects.create(
        task_id=task_id,
        task_name=f"AI报告推送: {report_title}",
        status=status_mapping.get(state, state),
        # retval 在失败时通常是 Exception 对象
        error_message=str(retval) if state == 'FAILURE' else "发送成功",
        created_at=timezone.now()
    )
    
@shared_task
def cleanup_old_logs():
    # 删除 30 天前的日志
    TaskLog.objects.filter(executed_at__lt=timezone.now() - timedelta(days=30)).delete()
 