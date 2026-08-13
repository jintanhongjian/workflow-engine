from typing import List, Sequence
import logging
import markdown
from .decorators import register_skill
from api_services.google_service import send_email

logger = logging.getLogger(__name__)


def _normalize_recipients(recipients: Sequence[str] | str) -> str:
    """Normalize recipients into a comma-separated string."""
    if isinstance(recipients, (list, tuple, set)):
        parts = [str(item).strip() for item in recipients if str(item).strip()]
        return ", ".join(parts)
    if isinstance(recipients, str):
        return recipients.strip()
    return ""


@register_skill
def send_email_skill(
    subject: str,
    body: str,
    recipients: Sequence[str] | str,
    attachments: List[str] | None = None,
    is_html: bool = False,
) -> str:
    """发送邮件；支持纯文本、HTML 或 Markdown 正文.

    - 当 `is_html=True` 时，`body` 作为 HTML 发送，同时提供空的纯文本备用。
    - 当 `is_html=False` 时，`body` 作为纯文本，同时自动渲染为 HTML（Markdown 转换）以便邮件客户端显示更佳。
    """
    recipients_emails = _normalize_recipients(recipients)
    if not recipients_emails:
        logger.error(f"Invalid recipients format: {recipients}")
        return "发送失败: 收件人格式无效"

    attachments = attachments or []

    plain_content = body if not is_html else ""
    html_content = body if is_html else markdown.markdown(body or "", extensions=["tables", "fenced_code"])

    try:
        send_email(
            to_email=recipients_emails,
            title=subject,
            plain_content=plain_content,
            html_content=html_content,
            attachment_paths=attachments,
        )
        return "发送完成: 成功 1, 失败 0"
    except Exception as exc:
        logger.error(f"发送至 {recipients_emails} 失败: {exc}")
        return f"发送失败: {exc}"
