from django.core.mail import get_connection, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from .models import EmailConfig
import logging

logger = logging.getLogger(__name__)

class DynamicMailService:
    @staticmethod
    def get_active_config():
        """获取当前启用的配置"""
        return EmailConfig.objects.filter(is_active=True).first()

    @classmethod
    def send_async_email(cls, subject, recipient_list, template_name, context, attachments=None):
        """
        支持自定义SMTP配置和附件发送
        :param attachments: 附件列表。支持以下两种格式：
            1. 本地路径字符串: ['/path/to/file.pdf']
            2. 自定义元组: [('filename.txt', content, 'text/plain')]
        """
        config = cls.get_active_config()
        if not config:
            raise ValueError("未找到启用的邮件服务器配置！")

        try:
            # 1. 动态构建连接句柄
            connection = get_connection(
                backend='django.core.mail.backends.smtp.EmailBackend',
                host=config.smtp_host,
                port=config.smtp_port,
                username=config.smtp_user,
                password=config.smtp_password,
                use_ssl=config.use_ssl,
            )

            # 2. 准备邮件内容
            html_content = render_to_string(template_name, context)
            text_content = strip_tags(html_content)
            from_email = f"{config.from_name} <{config.smtp_user}>"

            # 3. 创建邮件对象
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=from_email,
                to=recipient_list,
                connection=connection  # 关键：强制使用数据库读取的配置连接
            )
            msg.attach_alternative(html_content, "text/html")

            # 4. 添加附件逻辑
            if attachments:
                for attachment in attachments:
                    if isinstance(attachment, str):
                        # 格式1：通过文件路径直接添加
                        msg.attach_file(attachment)
                    elif isinstance(attachment, tuple):
                        # 格式2：通过元组添加 (文件名, 内容, MIME类型)
                        msg.attach(*attachment)

            # 5. 执行发送
            result = msg.send()
            logger.info(f"邮件已发送: {subject} 至 {recipient_list}")
            return result

        except Exception as e:
            logger.error(f"自定义邮件发送失败: {str(e)}")
            return False

class MailService:
    """
    集成动态配置与附件支持的工作流邮件服务
    """
    @staticmethod
    def _get_dynamic_connection(config):
        """内部方法：根据数据库配置创建 SMTP 连接"""
        return get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=config.smtp_host,
            port=config.smtp_port,
            username=config.smtp_user,
            password=config.smtp_password,
            use_ssl=config.use_ssl,
        )

    @classmethod
    def send_smtp_email(cls, subject, recipient_list, template_name, context, attachments=None):
        """
        核心发送方法
        :param subject: 邮件标题
        :param recipient_list: 接收人列表 [email1, email2]
        :param template_name: 模板路径
        :param context: 模板变量字典
        :param attachments: 附件列表 (路径或元组)
        """
        # 1. 获取启用的动态配置
        config = EmailConfig.objects.filter(is_active=True).first()
        if not config:
            logger.error("邮件发送失败：未找到启用的 EmailConfig 配置")
            return False

        try:
            # 2. 渲染邮件内容
            html_content = render_to_string(template_name, context)
            text_content = strip_tags(html_content)
            
            # 使用配置中的发件人名称和账号
            from_email = f"{config.from_name} <{config.smtp_user}>"

            # 3. 创建连接和邮件对象
            connection = cls._get_dynamic_connection(config)
            
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=from_email,
                to=recipient_list,
                connection=connection  # 关键：绑定动态连接
            )
            email.attach_alternative(html_content, "text/html")

            # 4. 处理附件
            if attachments:
                for attachment in attachments:
                    if isinstance(attachment, str):
                        # 格式1: 本地文件路径
                        email.attach_file(attachment)
                    elif isinstance(attachment, tuple) and len(attachment) == 3:
                        # 格式2: 自定义元组 (文件名, 内容, MIME类型)
                        email.attach(*attachment)
                    else:
                        logger.warning(f"跳过无效的附件格式: {attachment}")

            # 5. 执行发送
            count = email.send(fail_silently=False)
            logger.info(f"邮件发送成功: {subject} -> {recipient_list}")
            return count > 0

        except Exception as e:
            logger.error(f"邮件发送失败: {str(e)}", exc_info=True)
            return False