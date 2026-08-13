from celery import shared_task
from api_services.email_service import MailService

@shared_task
def send_async_email(subject, from_email, recipients, template, context,attachments=None):
    MailService.send_smtp_email(subject, from_email, recipients, template, context, attachments=attachments)