import json
import uuid
from datetime import datetime
from django.apps import apps
from django.contrib.auth.models import User
from django.db.models import Max
from api_services.templates import ScheduleType
from django.contrib.auth import get_user_model
from .decorators import register_skill


def get_current_user(id=None):
    User = get_user_model()
    if id:
        return User.objects.filter(id=id).first()
    return User.objects.filter(is_superuser=True).first() or User.objects.first()

@register_skill
def create_user_task(
    title: str,
    description: str = "",
    task_name: str | None = None,
    task_params: str = "{}",
    plan_type: str = "interval",
    interval: int = 1,
    interval_period: str = "Minutes",
    period_type: str = "",
    spec_date: str = "",
    is_recurring: bool = False,
    is_active: bool = True,
    user_id: int | None = None,
):
    """Create a UserScheduledTask for the current user using provided parameters.
    Parameters:
    - title: 任务标题。
    - description: 任务描述。
    - task_name: Celery 任务路径（例如 api_services.tasks.run_skill_task）。
    - task_params: 任务参数，必须是 JSON 对象字符串。
    - plan_type: 调度类型（ScheduleType.plan_type）。
    - interval: 如果使用 interval 调度，执行间隔数值。
    - interval_period: 如果使用 interval 调度，执行间隔单位(ScheduleType.INTERVAL_CHOICES)。
    - period_type: 其他调度类型的具体配置（ScheduleType.PERIOD_CHOICES）。
    - spec_date: 如果是一次性任务，指定执行的具体时间（ISO 格式字符串）。
    - is_recurring: 是否重复执行（仅对一次性任务有效）。
    - is_active: 任务是否启用。
    - user_id: 可选的用户 ID，指定任务创建者；如果未提供，则默认使用第一个超级用户或普通用户。
    Returns:
    - 成功时返回字符串 "Success: task '...' created with id=... for user=..."。
    - 失败时返回错误描述字符串。
    """
    if not task_name:
        return "Error: task_name is required and should point to the newly created skill (e.g., api_services.skills.my_skill)."
    user = get_current_user(user_id)
    if not user or not getattr(user, "id", None):
        user = User.objects.filter(is_superuser=True).first() or User.objects.first()
        if not user:
            return "Error: No available user to assign as creator."

    try:
        parsed_params = json.loads(task_params) if isinstance(task_params, str) else dict(task_params)
        if not isinstance(parsed_params, dict):
            return "Error: task_params must be JSON object."
    except Exception as exc:  # noqa: BLE001
        return f"Error: invalid task_params JSON - {exc}"

    spec_dt = None
    if spec_date:
        try:
            spec_dt = datetime.fromisoformat(spec_date)
        except Exception as exc:  # noqa: BLE001
            return f"Error: invalid spec_date format - {exc}"

    # Lazy-load model to avoid circular import during registry load
    UserScheduledTask = apps.get_model('api_services', 'UserScheduledTask')

    # Enforce skill_name when scheduling run_skill_task
    if task_name == 'api_services.tasks.run_skill_task':
        skill_name = parsed_params.get('skill_name')
        if not skill_name:
            return "Error: skill_name is required in task_params when using run_skill_task."

    task_kwargs = {
        "creator": user,
        "title": title,
        "description": description or title,
        "task_name": task_name,
        "task_params": parsed_params,
        "plan_type": plan_type or "interval",
        "interval": interval or 1,
        "interval_period": interval_period,
        "period_type": period_type or None,
        "spec_date": spec_dt,
        "is_recurring": bool(is_recurring),
        "is_active": bool(is_active),
    }

    # Dynamically handle ID generation to strictly avoid UNIQUE constraint failed errors
    pk_field = UserScheduledTask._meta.pk
    internal_type = pk_field.get_internal_type()
    pk_name = pk_field.name

    if internal_type in ("CharField", "TextField"):
        max_len = getattr(pk_field, 'max_length', 36)
        if max_len and max_len < 32:
            task_kwargs[pk_name] = str(uuid.uuid4().hex)[:max_len]
        else:
            task_kwargs[pk_name] = str(uuid.uuid4())
    elif internal_type == "UUIDField":
        task_kwargs[pk_name] = uuid.uuid4()
    elif internal_type in ("IntegerField", "BigAutoField", "SmallAutoField", "AutoField"):
        max_id = UserScheduledTask.objects.aggregate(max_id=Max(pk_name))['max_id']
        task_kwargs[pk_name] = (max_id or 0) + 1

    task = UserScheduledTask.objects.create(**task_kwargs)

    return f"Success: task '{task.title}' created with id={task.id} for user={user.username}."