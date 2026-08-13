# Register your models here.
from django.contrib import admin
import json
import os
from .models import (
    UserProfile,
    EmailConfig,
    DBConfig,
    UserScheduledTask,
    SkillExecutionLog,
    APIKey,
    TaskAttachment,
    TaskExecutionLog,
    AIChatMessage,
    AIChatConversation,
    SystemPrompt,
    ConversationMode,
)
from django import forms
from .tasks import list_task_specs


class TaskAttachmentForm(forms.ModelForm):
    class Meta:
        model = TaskAttachment
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['filename'].required = False

    def clean(self):
        cleaned_data = super().clean()
        filename = cleaned_data.get('filename')
        file_obj = cleaned_data.get('file')

        if not filename and file_obj:
            cleaned_data['filename'] = os.path.basename(file_obj.name)

        return cleaned_data


class TaskAttachmentInline(admin.TabularInline):
    model = TaskAttachment
    form = TaskAttachmentForm
    extra = 1
    fields = ('file', 'filename', 'uploaded_at')
    readonly_fields = ('uploaded_at',)


class UserScheduledTaskForm(forms.ModelForm):
    task_param_schema_preview = forms.CharField(
        label="任务参数说明",
        required=False,
        widget=forms.Textarea(attrs={'rows': 8, 'readonly': 'readonly'}),
        help_text="根据所选任务函数自动生成参数清单。",
    )

    class Meta:
        model = UserScheduledTask
        fields = '__all__'

    class Media:
        js = ('api_services/js/user_scheduled_task_admin.js',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        task_name = None
        if self.instance and self.instance.pk:
            task_name = self.instance.task_name
        else:
            task_name = self.initial.get('task_name') or self.data.get('task_name') or self.fields['task_name'].initial

        schema = []
        template = {}
        if task_name:
            temp_instance = self.instance if self.instance and self.instance.pk else UserScheduledTask(task_name=task_name)
            schema = temp_instance.get_task_param_schema()
            template = temp_instance.get_task_param_template()

        self.fields['task_name'].widget.attrs['data-task-specs'] = json.dumps(list_task_specs(), ensure_ascii=False)

        self.fields['task_param_schema_preview'].initial = json.dumps(schema, ensure_ascii=False, indent=2)
        self.fields['task_params'].help_text = "按 JSON 填写任务参数，推荐结构：\n" + json.dumps(template, ensure_ascii=False, indent=2)

        if not (self.instance and self.instance.pk) and not self.initial.get('task_params'):
            self.initial['task_params'] = template

@admin.register(SkillExecutionLog)
class SkillExecutionLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'skill_name', 'status', 'result_preview')
    list_filter = ('status', 'skill_name', 'timestamp')
    search_fields = ('skill_name', 'error_message', 'result_summary')
    readonly_fields = ('timestamp', 'arguments', 'error_message', 'result_summary')
    
    def result_preview(self, obj):
        return str(obj.result_summary)[:50]

@admin.register(TaskExecutionLog)
class TaskExecutionLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'task_name', 'status', 'result_summary')
    list_filter = ('status', 'task_name', 'timestamp')
    search_fields = ('task_name', 'error_message', 'result_summary')
    readonly_fields = ('timestamp', 'task', 'error_message', 'result_summary')
        

class AIChatMessageInline(admin.TabularInline):
    model = AIChatMessage
    extra = 0
    readonly_fields = ('role', 'text', 'created_at', 'user', 'conversation_id')
    fields = ('role', 'text', 'created_at', 'user', 'conversation_id')


@admin.register(AIChatConversation)
class AIChatConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'user', 'message_count', 'last_message_at')
    list_filter = ('user',)
    search_fields = ('id', 'title', 'last_text')
    readonly_fields = ('id', 'created_at', 'updated_at', 'last_message_at', 'last_role', 'last_text', 'message_count')
    inlines = (AIChatMessageInline,)


@admin.register(AIChatMessage)
class AIChatMessageAdmin(admin.ModelAdmin):
    list_display = ('conversation_id', 'role', 'user', 'created_at', 'text_preview')
    list_filter = ('role', 'created_at')
    search_fields = ('conversation_id', 'text', 'user__username')
    readonly_fields = ('conversation_id', 'user', 'role', 'text', 'created_at')
    ordering = ('-created_at',)

    def text_preview(self, obj):
        return (obj.text or '')[:80]


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'language', 'get_user_groups', 'get_permissions_count']
    
    def get_user_groups(self, obj):
        return ", ".join(obj.user_groups)
    get_user_groups.short_description = "用户组"

    def get_permissions_count(self, obj):
        perms = obj.permissions
        total = len(perms)
        if total > 0:
            return f"{total} 个权限"
        return "无权限"
    get_permissions_count.short_description = "权限数量"
    
class EmailConfigForm(forms.ModelForm):
    class Meta:
        model = EmailConfig
        widgets = {
            'smtp_password': forms.PasswordInput(render_value=True),
        }
        fields = '__all__'


class APIKeyForm(forms.ModelForm):
    class Meta:
        model = APIKey
        widgets = {
            'key': forms.PasswordInput(render_value=True),
        }
        fields = '__all__'

@admin.register(EmailConfig)
class EmailConfigAdmin(admin.ModelAdmin):
    form = EmailConfigForm
    list_display = ('smtp_user', 'smtp_host', 'smtp_port', 'from_name', 'is_default', 'is_active')
    
    def save_model(self, request, obj, form, change):
        # 如果当前配置设为启用，则自动禁用其他配置
        if obj.is_active:
            EmailConfig.objects.exclude(pk=obj.pk).update(is_active=False)
        super().save_model(request, obj, form, change)
        
@admin.register(DBConfig)
class DBConfigAdmin(admin.ModelAdmin):
    list_display = ('name', 'db_type', 'path', 'host', 'port', 'is_active')
    def save_model(self, request, obj, form, change):
        # 如果当前配置设为启用，则自动禁用其他配置
        if obj.is_active:
            DBConfig.objects.exclude(pk=obj.pk).update(is_active=False)
        super().save_model(request, obj, form, change)
        
        
@admin.register(UserScheduledTask)
class UserScheduledTaskAdmin(admin.ModelAdmin):
    form = UserScheduledTaskForm
    list_display = ('title', 'creator', 'task_name', 'plan_type', 'get_schedule_desc', 'last_run_at', 'is_active', 'updated_at')
    list_filter = ('plan_type', 'is_active', 'is_recurring', 'updated_at')
    search_fields = ('title', 'description', 'task_name')
    # 开启自动完成，方便在几百个周期设置里找
    # autocomplete_fields = ['crontab_schedule']
    
    fieldsets = (
        ("基本信息", {'fields': ('creator', 'title', 'description', 'task_name', 'task_param_schema_preview', 'task_params', 'is_active')}),
        ("调度配置", {
            'fields': ('plan_type', ('interval', 'interval_period',), 'period_type', ('spec_date', 'is_recurring')),
            'description': "根据计划类型配置执行策略；保存后会自动生成对应的 Celery 调度。"
        }),
        ("系统关联", {
            'fields': ('interval_schedule', 'crontab_schedule', 'periodic_task', 'last_run_at', 'updated_at'),
            'description': "以下字段由系统自动维护。"
        }),
    )
    readonly_fields = ('interval_schedule', 'crontab_schedule', 'periodic_task', 'last_run_at', 'updated_at')
    inlines = (TaskAttachmentInline,)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.save()

    def get_schedule_desc(self, obj):
        if obj.plan_type == 'realtime':
            return "实时"
        if obj.interval_schedule:
            return str(obj.interval_schedule)
        if obj.crontab_schedule:
            return str(obj.crontab_schedule)
        return "未配置"
    get_schedule_desc.short_description = "重复周期"

@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    form = APIKeyForm
    list_display = ('name', 'masked_key', 'is_active', 'description', 'base_url')
    list_filter = ('is_active',)
    search_fields = ('name', 'description', 'base_url')

    def masked_key(self, obj):
        if not obj.key:
            return ''
        if len(obj.key) <= 8:
            return '*' * len(obj.key)
        return f"{obj.key[:4]}...{obj.key[-4:]}"
    masked_key.short_description = 'Key(脱敏)'

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(TaskAttachment)
class TaskAttachmentAdmin(admin.ModelAdmin):
    form = TaskAttachmentForm
    list_display = ('filename', 'task', 'uploaded_at')
    list_filter = ('uploaded_at',)
    search_fields = ('filename', 'task__title')
    readonly_fields = ('uploaded_at',)


@admin.register(SystemPrompt)
class SystemPromptAdmin(admin.ModelAdmin):
    list_display = ('role_name', 'is_active', 'is_default', 'updated_at')
    list_filter = ('is_active', 'is_default')
    search_fields = ('role_name', 'role_definition', 'prompt_content')
    ordering = ('-updated_at',)


@admin.register(ConversationMode)
class ConversationModeAdmin(admin.ModelAdmin):
    list_display = ('code', 'label', 'is_active', 'default_system_prompt', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('code', 'label', 'description')
    autocomplete_fields = ('default_system_prompt',)
    ordering = ('code',)