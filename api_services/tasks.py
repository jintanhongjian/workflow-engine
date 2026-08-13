from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from celery.signals import task_postrun
from django.db import transaction
from django.contrib import messages
from .google_service import send_email
from .skills.registry import registry
from .models import SkillExecutionLog, TaskExecutionLog
import logging
import sys
import inspect
from typing import Any

logger = logging.getLogger(__name__)


def _is_shared_task(obj: Any) -> bool:
    return hasattr(obj, 'delay') and hasattr(obj, 'name') and callable(obj)


def _format_annotation(annotation: Any) -> str:
    if annotation is inspect._empty:
        return 'Any'
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation)


def _extract_task_params(task_obj: Any):
    params = []
    signature = inspect.signature(task_obj.run)
    for param_name, param in signature.parameters.items():
        if param_name == 'self':
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        has_default = param.default is not inspect._empty
        params.append({
            'name': param_name,
            'required': not has_default,
            'default': None if not has_default else param.default,
            'type': _format_annotation(param.annotation),
            'kind': str(param.kind),
        })
    return params


def list_task_specs():
    """
    Discover Celery tasks in this module.
    Returns:
        {
            "module.task_name": {
                "label": "Task Label",
                "params": [{"name": ..., "required": ..., "default": ..., "type": ...}]
            }
        }
    """
    task_specs = {}
    current_module = sys.modules[__name__]

    for name, obj in inspect.getmembers(current_module):
        if _is_shared_task(obj):
            task_name = obj.name
            label = (inspect.getdoc(obj) or name).split('\n')[0]
            task_specs[task_name] = {
                'label': label,
                'params': _extract_task_params(obj),
            }

    return task_specs

# 自动读取本文件获取任务函数列表
def task_list():
    """
    Dynamically discover Celery tasks in this module and return a list of (task_name, description) tuples.
    """
    task_specs = list_task_specs()
    return [(task_name, spec['label']) for task_name, spec in task_specs.items()]

def task_param_schema(task_name: str):
    """Return parameter schema list for target task."""
    return list_task_specs().get(task_name, {}).get('params', [])


def task_param_template(task_name: str):
    """
    Build a default JSON template for task_params.
    Required params default to empty string, optional params use declared defaults.
    """
    template = {}
    for param in task_param_schema(task_name):
        if param['required']:
            template[param['name']] = ''
        else:
            template[param['name']] = param['default']
    return template


# 发送邮件提醒的任务
@shared_task
def task_email_reminder(
    email_subject: str,
    email_body: str,
    recipient_list: str,
    attachments: list = None,
    db_id: int = None,
    **kwargs,
    ):
    try:
        normalized_recipients = []
        if isinstance(recipient_list, str):
            normalized_recipients = [item.strip() for item in recipient_list.split(',') if item.strip()]
        elif isinstance(recipient_list, (list, tuple, set)):
            for item in recipient_list:
                if isinstance(item, str):
                    normalized_recipients.extend([part.strip() for part in item.split(',') if part.strip()])
                elif item is not None:
                    normalized_recipients.append(str(item).strip())
        elif recipient_list is not None:
            normalized_recipients = [str(recipient_list).strip()]

        body_text = '' if email_body is None else str(email_body)
        body_html = body_text.replace('\n', '<br>')
        attachment_paths = attachments or []

        if not normalized_recipients:
            logger.warning("Email reminder skipped: empty recipient_list")
            return False

        success = True
        for to_email in normalized_recipients:
            sent = send_email(
                to_email=to_email,
                title=email_subject,
                plain_content=body_text,
                html_content=body_html,
                attachment_paths=attachment_paths,
            )
            success = success and bool(sent)

        return success
    except Exception as e:
        logger.error(f"Failed to send email reminder: {e}")
        return False


@shared_task(name="api_services.tasks.run_skill_task")
def run_skill_task(skill_name: str | None = None, skill_kwargs: dict | None = None, db_id: int | None = None, **extra):
    """Execute skill function by name (system tasks for AI workbench)."""
    try:
        payload = dict(skill_kwargs or {}) if skill_kwargs else {}
        # Allow skill_name to be provided either as explicit arg or inside payload/extra
        skill_name = skill_name or payload.pop('skill_name', None) or extra.get('skill_name')

        if not skill_name:
            return "Error: skill_name is required for run_skill_task."

        func = registry.functions_dict.get(skill_name)
        if not func:
            return f"Error: skill '{skill_name}' not found in registry."

        if not isinstance(payload, dict):
            return "Error: skill_kwargs must be a JSON object."
        task_obj = None
        if db_id is not None:
            try:
                from .models import UserScheduledTask  # lazy import to avoid circulars
                task_obj = UserScheduledTask.objects.filter(pk=db_id).first()
            except Exception as _exc:
                logger.warning(f"run_skill_task log: cannot load UserScheduledTask({db_id}): {_exc}")

        def _log(status: str, result_summary: str = '', error_message: str = ''):
            if not task_obj:
                return
            try:
                TaskExecutionLog.objects.create(
                    task=task_obj,
                    task_name=task_obj.task_name,
                    status=status,
                    result_summary=result_summary,
                    error_message=error_message,
                )
            except Exception as log_exc:
                logger.warning(f"run_skill_task log failed (task_id={db_id}): {log_exc}")

        try:
            result = func(**payload)
        except Exception as call_exc:
            err_msg = f"Error executing skill '{skill_name}': {call_exc}"
            logger.error(err_msg)
            _log('FAILURE', result_summary='', error_message=str(call_exc))
            return err_msg

        # Interpret result for success/failure heuristics
        if isinstance(result, str) and any(keyword in result.lower() for keyword in ['error', 'fail', 'exception']):
            _log('FAILURE', result_summary='', error_message=str(result))
            return f"Error executing skill '{skill_name}': {result}"

        _log('SUCCESS', result_summary=str(result)[:1000] if result is not None else '')
        return result
    except Exception as exc:
        logger.error(f"Failed to run skill '{skill_name}': {exc}")
        return f"Error executing skill '{skill_name}': {exc}"

@task_postrun.connect
def update_task_last_run_at(sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **extra):
    """After task execution, update UserScheduledTask.last_run_at and create a TaskExecutionLog entry."""
    if not kwargs:
        return

    db_id = kwargs.get('db_id')
    if not db_id:
        return

    try:
        task_pk = int(db_id)
    except (TypeError, ValueError):
        return

    try:
        from .models import UserScheduledTask, TaskExecutionLog
        
        # 1. Update user task stats
        UserScheduledTask.objects.filter(pk=task_pk).update(last_run_at=timezone.now())

        # 2. Create execution log
        task_obj = UserScheduledTask.objects.filter(pk=task_pk).first()
        if task_obj:
            status = 'SUCCESS' if state == 'SUCCESS' else 'FAILURE'
            
            result_str = str(retval) if retval is not None else ''
            error_str = ''
            if state == 'FAILURE':
                error_str = str(retval)
                result_str = '' 

            TaskExecutionLog.objects.create(
                task=task_obj,
                task_name=task.name if task else task_obj.task_name,
                status=status,
                result_summary=result_str,
                error_message=error_str,
            )

    except Exception as exc:
        logger.warning(f"Failed to update last_run_at or create log for UserScheduledTask({task_pk}): {exc}")

