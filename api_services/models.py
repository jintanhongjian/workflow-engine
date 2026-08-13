from django.db import models, connections
from django.conf import settings
from approve_flow.models import Department
from django.contrib.auth.models import User
from django_celery_beat.models import PeriodicTask, CrontabSchedule, IntervalSchedule
from django.utils.functional import lazy
from .templates import ScheduleType
import json
import os
import pytz
import uuid


def _task_list():
    from .tasks import task_list
    return task_list()


def _task_param_schema(task_name):
    from .tasks import task_param_schema
    return task_param_schema(task_name)


def _task_param_template(task_name):
    from .tasks import task_param_template
    return task_param_template(task_name)


task_list_lazy = lazy(_task_list, list)

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    # 存储语言代码，如 'en' 或 'zh-hans'
    language = models.CharField(max_length=10, default='zh-hans')

    @property
    def permissions(self):
        """
        获取用户的所有权限，包括直接分配给用户的权限和通过用户组继承的权限。
        """
        if self.user.is_superuser:
            return ['all']
            
        perms = set()
        
        # 1. 获取用户直接拥有的权限
        user_perms = self.user.user_permissions.all()
        for perm in user_perms:
            perms.add(f"{perm.content_type.app_label}.{perm.codename}")
            
        # 2. 获取用户通过组继承的权限
        group_perms = getattr(self.user, 'groups', None)
        if group_perms:
            for group in group_perms.all():
                for perm in group.permissions.all():
                    perms.add(f"{perm.content_type.app_label}.{perm.codename}")
                    
        return list(perms)

    @property
    def user_groups(self):
        """
        获取用户所属的所有组名称
        """
        groups = getattr(self.user, 'groups', None)
        if groups:
            return [group.name for group in groups.all()]
        return []

    class Meta:
        verbose_name = "用户配置"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.user.username}'s Profile"

class EmailConfig(models.Model):
    """全局邮件服务器配置"""
    smtp_host = models.CharField(max_length=255, default='smtp.exmail.qq.com', verbose_name="SMTP服务器")
    smtp_port = models.PositiveIntegerField(default=465, verbose_name="端口")
    smtp_user = models.EmailField(verbose_name="发件账号")
    smtp_password = models.CharField(max_length=255, verbose_name="授权码/密码")
    use_ssl = models.BooleanField(default=False, verbose_name="使用SSL")
    use_tls = models.BooleanField(default=True, verbose_name="使用TLS")
    from_name = models.CharField(max_length=100, default="审批系统", verbose_name="发件人显示名称")
    is_default = models.BooleanField(default=False, verbose_name="是否默认配置")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")

    class Meta:
        verbose_name = "邮件服务器配置"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.smtp_user} ({self.smtp_host})"

class SkillExecutionLog(models.Model):
    """Logs every execution of an AI skill function."""
    exe_status=[('SUCCESS', 'Success'), ('FAILED', 'Failed'), ('AUTO-FIXED', 'Auto-Fixed')]
    
    skill_name = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)
    arguments = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=50, choices=exe_status)
    error_message = models.TextField(null=True, blank=True)
    result_summary = models.TextField(null=True, blank=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = "Skill Execution Log"
        verbose_name_plural = "技能执行日志"

    def __str__(self):
        return f"{self.timestamp} - {self.skill_name} ({self.status})"

class DBConfig(models.Model):
    """数据库连接配置"""
    name = models.CharField(max_length=100, unique=True, verbose_name="配置名称")
    db_type = models.CharField(max_length=50, choices=[('sqlite', 'SQLite'), 
                                                       ('postgres', 'PostgreSQL'),
                                                        ('mysql', 'MySQL'),
                                                        ('mongodb', 'MongoDB'),
                                                        ('sqlserver', 'SQL Server'),
                                                        ('oracle', 'Oracle')],
                               default='sqlite', verbose_name="数据库类型")
    path = models.CharField(max_length=255, blank=True, null=True, verbose_name="SQLite文件路径")
    host = models.CharField(max_length=255, blank=True, null=True, verbose_name="主机地址")
    port = models.PositiveIntegerField(blank=True, null=True, verbose_name="端口")
    username = models.CharField(max_length=255, blank=True, null=True, verbose_name="用户名")
    password = models.CharField(max_length=255, blank=True, null=True, verbose_name="密码")
    database_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="数据库名称")

    is_active = models.BooleanField(default=True, verbose_name="是否启用")

    class Meta:
        verbose_name = "数据库连接配置"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.name} ({self.db_type})"

    def get_connection(self):
        """
        根据配置返回数据库连接对象 (主要是 DB-API 2.0 兼容连接)
        """
        if self.db_type == 'sqlite':
            import sqlite3
            if not self.path:
                raise ValueError("SQLite database path is required")
            return sqlite3.connect(self.path)
        
        elif self.db_type == 'postgres':
            import psycopg2
            return psycopg2.connect(
                host=self.host,
                port=self.port or 5432,
                user=self.username,
                password=self.password,
                database=self.database_name
            )
        
        elif self.db_type == 'mysql':
            # 需要安装 mysql-connector-python 或 pymysql
            # 这里尝试 mysql.connector
            try:
                import mysql.connector
                return mysql.connector.connect(
                    host=self.host,
                    port=self.port or 3306,
                    user=self.username,
                    password=self.password,
                    database=self.database_name
                )
            except ImportError:
                # 尝试 pymysql
                import pymysql
                return pymysql.connect(
                    host=self.host,
                    port=self.port or 3306,
                    user=self.username,
                    password=self.password,
                    database=self.database_name
                )

        elif self.db_type == 'sqlserver':
            import pymssql
            return pymssql.connect(
                server=self.host,
                port=self.port or 1433,
                user=self.username,
                password=self.password,
                database=self.database_name
            )

        elif self.db_type == 'oracle':
            import oracledb
            dsn = oracledb.makedsn(self.host, self.port or 1521, service_name=self.database_name)
            return oracledb.connect(
                user=self.username,
                password=self.password,
                dsn=dsn
            )

        elif self.db_type == 'mongodb':
            from pymongo import MongoClient
            # MongoDB 返回的是 Client 对象，不是标准 DB-API 连接
            # connection string format: mongodb://username:password@host:port/database_name
            if self.username and self.password:
                uri = f"mongodb://{self.username}:{self.password}@{self.host}:{self.port or 27017}/{self.database_name}"
            else:
                uri = f"mongodb://{self.host}:{self.port or 27017}/{self.database_name}"
            return MongoClient(uri)

        else:
            raise NotImplementedError(f"Database type {self.db_type} is not supported yet.")


    def ensure_connection(self):
        """
        动态将此 DBConfig 注册到 Django 的 DATABASES 配置中。
        使用时，在查询中指定 .using(self.name) 即可。
        
        用法:
            db_config = DBConfig.objects.get(name='sales_db')
            db_config.ensure_connection()
            # 然后就可以用ORM查询了 (注意Model必须对应对方数据库的表结构)
            User.objects.using('sales_db').all()
        """
        if self.name in settings.DATABASES:
            # 如果配置已经在 settings 里了，可能是之前加载过，直接返回
            # 但为了防止配置修改后未生效，我们这里可以选择通过
            pass

        # 构建标准的 Django DATABASE 配置字典
        new_db_conf = {
            'ENGINE': '',
            'NAME': self.database_name,
            'USER': self.username,
            'PASSWORD': self.password,
            'HOST': self.host,
            'PORT': self.port,
            'ATOMIC_REQUESTS': False, # 动态连接建议关闭事务自动管理
            'AUTOCOMMIT': True,
            'CONN_MAX_AGE': 0, # 不池化连接，用完即关，防止资源泄露
        }

        if self.db_type == 'postgres':
            new_db_conf['ENGINE'] = 'django.db.backends.postgresql'
        elif self.db_type == 'mysql':
            new_db_conf['ENGINE'] = 'django.db.backends.mysql'
        elif self.db_type == 'sqlite':
            new_db_conf['ENGINE'] = 'django.db.backends.sqlite3'
            new_db_conf['NAME'] = self.path # SQLite 使用 path 而不是 database_name
        elif self.db_type == 'oracle':
            new_db_conf['ENGINE'] = 'django.db.backends.oracle'
        else:
             # MongoDB 和 SQLServer(django-mssql-backend) 需要额外处理，这里暂只支持标准SQL
            raise ValueError(f"Django ORM dynamic connection supports [postgres, mysql, sqlite, oracle], not {self.db_type}")

        # 1. 注入到 settings.DATABASES (这也正是 Django 查找数据库配置的地方)
        settings.DATABASES[self.name] = new_db_conf

        # 2. 并在 connections 中刷新 (如果之前有旧连接，关闭它)
        if self.name in connections:
            del connections[self.name] # 删除旧的句柄，迫使 Django 下次重新建立连接

# 附件模型
class TaskAttachment(models.Model):
    task = models.ForeignKey('UserScheduledTask', on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='task_attachments/%Y/%m/%d/', verbose_name="附件文件")
    filename = models.CharField(max_length=255, blank=True, default='', verbose_name="原始文件名")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "任务附件"
        verbose_name_plural = verbose_name

    def save(self, *args, **kwargs):
        if self.file and (not self.filename or self.filename == 'file'):
            self.filename = os.path.basename(self.file.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.filename

# 2. 核心任务模型
class UserScheduledTask(models.Model):
    creator = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="创建者")
    title = models.CharField(max_length=200, verbose_name="任务名称")
    task_name = models.CharField(
        max_length=255, 
        choices=task_list_lazy(),
        default='api_services.tasks.task_email_reminder', 
        verbose_name="Celery任务路径"
    )
    # 任务函数参数对象
    task_params = models.JSONField(default=dict, blank=True, verbose_name="任务参数（JSON格式）")
    description = models.TextField(verbose_name="任务详细说明")

    crontab_schedule = models.ForeignKey(
        CrontabSchedule, 
        on_delete=models.CASCADE, 
        verbose_name="Crontab周期设置",
        blank=True,
        null=True
    )

    interval_schedule = models.ForeignKey(
        IntervalSchedule,
        on_delete=models.CASCADE,
        verbose_name="Interval间隔设置",
        blank=True,
        null=True,
    )
    
    # New scheduling fields
    plan_type = models.CharField(max_length=20, choices=ScheduleType.plan_type, default='interval', verbose_name="调度类型")
    interval = models.PositiveIntegerField(default=1, verbose_name="间隔数值")
    interval_period = models.CharField(max_length=20, choices=ScheduleType.INTERVAL_CHOICES, blank=True, null=True, verbose_name="间隔单位")
    period_type = models.CharField(max_length=20, choices=ScheduleType.PERIOD_CHOICES, blank=True, null=True, verbose_name="周期单位")
    spec_date = models.DateTimeField(blank=True, null=True, verbose_name="指定执行时间")
    is_recurring = models.BooleanField(default=False, verbose_name="是否循环执行")

    periodic_task = models.OneToOneField(
        PeriodicTask, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name="business_metadata"
    )

    is_active = models.BooleanField(default=True, verbose_name="启用状态")
    last_run_at = models.DateTimeField(blank=True, null=True, verbose_name="上次执行时间")
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "用户定时任务"
        verbose_name_plural = verbose_name

    def get_task_param_schema(self):
        return _task_param_schema(self.task_name)

    def get_task_param_template(self):
        return _task_param_template(self.task_name)

    def get_attachment_param_names(self):
        default_names = ['attachments', 'attachment', 'files', 'file_paths', 'docs', 'documents']
        names = getattr(settings, 'TASK_ATTACHMENT_PARAM_NAMES', default_names)
        return {str(name).strip().lower() for name in names if str(name).strip()}

    def get_attachment_param_keywords(self):
        default_keywords = ['attachment', 'file', 'doc']
        keywords = getattr(settings, 'TASK_ATTACHMENT_PARAM_KEYWORDS', default_keywords)
        return [str(keyword).strip().lower() for keyword in keywords if str(keyword).strip()]

    def is_attachment_param(self, param_name):
        normalized = str(param_name or '').strip().lower()
        if not normalized:
            return False

        if normalized in self.get_attachment_param_names():
            return True

        return any(keyword in normalized for keyword in self.get_attachment_param_keywords())

    def save(self, *args, **kwargs):
        # 1. 自动生成/管理 Schedule
        self.crontab_schedule = None
        self.interval_schedule = None

        if self.plan_type != 'realtime':
            # 准备参数
            schedule_kwargs = {
                'plan_type': self.plan_type,
                'interval': self.interval,
                'interval_period': self.interval_period,
                'period': self.period_type,
                'spec_date': self.spec_date,
                'is_recurring': self.is_recurring
            }
            
            # 使用改造后的 get_schedule_config 获取配置
            schedule_config = ScheduleType.get_schedule_config(**schedule_kwargs)
            
            if schedule_config['type'] == 'interval':
                interval_obj, _ = IntervalSchedule.objects.get_or_create(**schedule_config['params'])
                self.interval_schedule = interval_obj
                
            elif schedule_config['type'] == 'crontab':
                crontab_params = dict(schedule_config['params'])
                if 'timezone' not in crontab_params:
                    tz_value = getattr(settings, 'CELERY_TIMEZONE', None) or getattr(settings, 'TIME_ZONE', 'UTC')
                    if isinstance(tz_value, str):
                        try:
                            tz_value = pytz.timezone(tz_value)
                        except Exception:
                            tz_value = pytz.timezone('UTC')
                    crontab_params['timezone'] = tz_value

                schedule_obj, _ = CrontabSchedule.objects.get_or_create(**crontab_params)
                self.crontab_schedule = schedule_obj
        
        # 首先保存自身以获取 ID (如果是新创建)
        is_new = self.pk is None
        if is_new:
            # 先进行基础保存
            super().save(*args, **kwargs)

        # 2. 构造传递给 Celery Task 的参数
        # 优先使用 task_params，它是用户定义的任务参数
        if not self.task_params:
            self.task_params = self.get_task_param_template()
        
        # 确保 task_kwargs 是字典
        if isinstance(self.task_params, str):
            try:
                task_kwargs = json.loads(self.task_params)
            except json.JSONDecodeError:
                task_kwargs = {}
        else:
            task_kwargs = self.task_params.copy()  # Copy to avoid modifying the original dict

        # 如果任务参数中包含附件字段，优先使用 TaskAttachment 上传的附件
        try:
            attachment_paths = [att.file.path for att in self.attachments.all() if att.file]
        except Exception:
            attachment_paths = []

        for param in self.get_task_param_schema():
            param_name = param.get('name', '')
            if not param_name:
                continue

            if not self.is_attachment_param(param_name):
                continue

            param_type = str(param.get('type', '')).lower()
            if 'list' in param_type:
                task_kwargs[param_name] = attachment_paths
            else:
                task_kwargs[param_name] = attachment_paths[0] if attachment_paths else None

        # 注入基础上下文参数 (如任务ID)
        task_kwargs['db_id'] = self.id
        
        # 3. 同步 Celery PeriodicTask
        task_unique_name = f"UserReminder_{self.title}_{self.id}"
        task_kwargs_json = json.dumps(task_kwargs)
        
        # 如果没有有效的调度配置（如 realtime 或未生效配置），不创建 periodic task
        should_have_task = (self.interval_schedule or self.crontab_schedule)

        if should_have_task:
            periodic_defaults = {
                'name': task_unique_name,
                'task': self.task_name,
                'kwargs': task_kwargs_json,
                'enabled': self.is_active,
            }

            if self.interval_schedule:
                periodic_defaults['interval'] = self.interval_schedule
                periodic_defaults['crontab'] = None
            elif self.crontab_schedule:
                periodic_defaults['crontab'] = self.crontab_schedule
                periodic_defaults['interval'] = None
            
            if not self.periodic_task:
                self.periodic_task = PeriodicTask.objects.create(**periodic_defaults)
            else:
                pt = self.periodic_task
                pt.interval = self.interval_schedule
                pt.crontab = self.crontab_schedule
                pt.enabled = self.is_active
                pt.kwargs = task_kwargs_json
                pt.task = self.task_name
                pt.save()
        else:
            # 如果之前有任务但现在配置无效了（比如改为 realtime），删除旧任务
            if self.periodic_task:
                self.periodic_task.delete()
                self.periodic_task = None
            
        # 再次保存以记录关联的 periodic_task
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # 删除时清理附件物理文件
        for att in self.attachments.all():
            att.file.delete()
        if self.periodic_task:
            self.periodic_task.delete()
        super().delete(*args, **kwargs)

class TaskExecutionLog(models.Model):
    """Logs execution of UserScheduledTask."""
    task = models.ForeignKey(UserScheduledTask, on_delete=models.CASCADE, related_name='execution_logs', verbose_name="关联任务")
    task_name = models.CharField(max_length=255, verbose_name="任务名称/标识")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="执行时间")
    status = models.CharField(max_length=50, choices=[('SUCCESS', 'Success'), ('FAILURE', 'Failed'), ('STARTED', 'Started')], verbose_name="执行状态")
    result_summary = models.TextField(null=True, blank=True, verbose_name="结果摘要")
    error_message = models.TextField(null=True, blank=True, verbose_name="错误信息")

    class Meta:
        ordering = ['-timestamp']
        verbose_name = "任务执行日志"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.timestamp} - {self.task_name} ({self.status})"
    
    @property
    def skill_name(self):
        return self.task_name

class APIKey(models.Model):
    """API Keys for external services"""
    name = models.CharField(max_length=100, unique=True, verbose_name="Key Name")
    key = models.CharField(max_length=255, verbose_name="API Key")
    base_url = models.CharField(max_length=255, blank=True, null=True, verbose_name="Base URL (if applicable)")
    is_active = models.BooleanField(default=True, verbose_name="Is Active")
    description = models.TextField(blank=True, null=True, verbose_name="Description")

    class Meta:
        verbose_name = "API Key"
        verbose_name_plural = "接口密钥"

    def __str__(self):
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"


class SystemPrompt(models.Model):
    """System prompts for Gemini content generation."""

    role_name = models.CharField(max_length=150, unique=True, verbose_name="角色名称")
    role_definition = models.TextField(verbose_name="角色定义")
    prompt_content = models.TextField(verbose_name="提示词内容")
    purpose = models.CharField(max_length=50, blank=True, null=True, verbose_name="用途分类")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    is_default = models.BooleanField(default=False, verbose_name="是否默认")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = "AI System Prompt"
        verbose_name_plural = "AI-系统提示词"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            SystemPrompt.objects.exclude(pk=self.pk).update(is_default=False)

    def __str__(self):
        return self.role_name

class ConversationMode(models.Model):
    """Predefined conversation modes for AI workbench."""

    code = models.CharField(
        max_length=64,
        unique=True,
        verbose_name="模式代码",
        help_text="如 run_intelligent_task / skill_call / get_content",
    )
    label = models.CharField(max_length=128, verbose_name="模式名称")
    description = models.TextField(blank=True, default='', verbose_name="模式说明")
    default_system_prompt = models.ForeignKey(
        SystemPrompt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conversation_modes',
        verbose_name="默认系统提示词",
    )
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        verbose_name = "AI conversation mode"
        verbose_name_plural = "AI-对话模式"

    def __str__(self):
        return f"{self.label} ({self.code})"

class AIChatConversation(models.Model):
    """Conversation summary for AI workbench."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=255, blank=True, default='')
    conversation_mode = models.CharField(
        max_length=32,
        default='run_intelligent_task',
        choices=[
            ('run_intelligent_task', '智能任务'),
            ('skill_call', '技能调用'),
            ('get_content', '内容生成'),
        ],
        verbose_name="对话模式",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_role = models.CharField(max_length=20, blank=True, default='')
    last_text = models.TextField(blank=True, default='')
    key_words = models.CharField(max_length=255, blank=True, default='', verbose_name="对话关键词")
    chat_memory = models.JSONField(default=list, blank=True, verbose_name="对话记忆（JSON格式）")
    message_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = "AI Chat Conversation"
        verbose_name_plural = "AI-会话"

    def __str__(self):
        return f"{self.id} ({self.title or 'AI Chat'})"

class AIChatMessage(models.Model):
    """Store AI workbench conversations per message."""
    conversation = models.ForeignKey(
        AIChatConversation,
        on_delete=models.CASCADE,
        related_name='messages',
        null=True,
        blank=True,
        db_column='conversation_id',
    )
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    system_prompt = models.ForeignKey(
        SystemPrompt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_messages',
        verbose_name="系统提示词",
    )
    role = models.CharField(max_length=20)  # user / assistant
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = "AI Chat Message"
        verbose_name_plural = "AI-会话消息"

    def __str__(self):
        return f"{self.conversation_id} {self.role} @{self.created_at}"

    def save(self, *args, **kwargs):
        if not self.conversation and hasattr(self, 'conversation_id'):
            try:
                self.conversation = AIChatConversation.objects.get(id=self.conversation_id)
            except Exception:
                pass
        super().save(*args, **kwargs)


