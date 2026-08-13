import os
from google import genai
from django.conf import settings
from api_services import gemini_service, google_service
from .models import Subscription, ReferenceDocument, ReportHistory
import logging
logger = logging.getLogger(__name__)

def generate_subscription_report(subscription,language='中文'):
    """
    基于订阅配置调用 Gemini 生成 Markdown 报告
    """
    from .models import ReportHistory
    # 2. 构建提示词 (Prompt)
    # 整合订阅的关键字、描述和上下文
    context = f"""
    你是一个专业的情报分析师。
    请基于以下信息生成一份 Markdown 格式的深度简报：
    主题：{subscription.report_title}
    核心关键词：{subscription.keywords}
    任务描述：{subscription.description}
    输出语言：{language}
    要求：结构清晰，包含摘要、关键动态、生动图片，数据图表，深度分析和建议。
    输出格式：使用标准的 Markdown 语法。
    """
    # 4. 调用 API 生成
    markdown_text = gemini_service.get_content(context)

    # 5. 自动存入历史记录表
    report = ReportHistory.objects.create(
        subscription=subscription,
        recipients=subscription.user_email,
        content_markdown=markdown_text,
        summary=markdown_text[:100] + "..." # 自动截取前100字作为摘要
    )
    return report

def generate_report_with_attachments(subscription,language='中文'):
    """
    将订阅关联的附件发送给 Gemini 进行深度分析生成报告
    """
    # 1. 准备多模态内容列表
    # 列表的第一个元素是我们的 Prompt 指令
    context = f"""
    你是一个专业的情报分析师。请基于以下信息生成一份 Markdown 格式的深度简报：
    主题：{subscription.report_title}
    核心关键词：{subscription.keywords}
    任务描述：{subscription.description}
    输出语言：{language}
    要求：结构清晰，包含摘要、关键动态、生动图片，数据图表，深度分析和建议。
    输出格式：使用标准的 Markdown 语法。
    """
    # 2. 遍历并上传附件
    # 获取该订阅下的所有关联文档
    docs = subscription.documents.all()
    # 发送请求
    # content_parts 包含了文字指令和多个文件对象
    markdown_text = gemini_service.get_content(context, documents=docs)

    #存入数据库
    if not markdown_text:
        raise Exception("Gemini API 未返回任何内容，可能调用失败。")   
    report = ReportHistory.objects.create(
        subscription=subscription,
        recipients=subscription.user_email,
        content_markdown=markdown_text,
        summary=markdown_text[:100] + "..."
    )
    return report

def send_report_email(recipient_emails, report_title, md_content):
    """
    合并发送邮件任务
    """
    try:
        google_service.send_markdown_report(
            to_email=recipient_emails,
            report_title=report_title,
            md_content=md_content
        )
    except Exception as exc:
        logger.error(f"发送至 {recipient_emails} 失败.")
        # 抛出重试异常，countdown=60 表示 60 秒后重试
    return f"发送完成: 成功 {success_count}, 失败 {fail_count}" 