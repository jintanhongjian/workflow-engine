import json
import re
from collections import Counter
from datetime import datetime
from types import SimpleNamespace
from django import forms
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import StreamingHttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import translation, timezone
from django.conf import settings
from django.core.files.storage import default_storage
from django.views.decorators.http import require_POST
from celery import current_app
import threading
from queue import SimpleQueue
from .models import (
    TaskAttachment,
    UserProfile,
    UserScheduledTask,
    TaskExecutionLog,
    AIChatMessage,
    AIChatConversation,
    SystemPrompt,
    ConversationMode,
)
from django.views.generic import ListView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
import uuid
from .tasks import task_list, task_param_schema, task_param_template
from .gemini_service import run_intelligent_task, skill_call, get_content
from .templates import ApiResponse
from api_services.skills.registry import registry as skill_registry


class CustomTaskCreateForm(forms.ModelForm):
    task_params = forms.CharField(
        label=_("任务参数(JSON)"),
        required=False,
        initial='{}',
        widget=forms.HiddenInput(),
        help_text=_("请输入 JSON 对象，例如 {\"to\": [\"a@b.com\"]}"),
    )

    class Meta:
        model = UserScheduledTask
        fields = [
            'title',
            'description',
            'task_name',
            'task_params',
            'plan_type',
            'interval',
            'interval_period',
            'period_type',
            'spec_date',
            'is_recurring',
            'is_active',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'spec_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_class = 'w-full rounded border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'
        checkbox_class = 'h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500'
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.HiddenInput):
                continue
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = checkbox_class
            else:
                widget.attrs['class'] = base_class

    def clean_task_params(self):
        value = self.cleaned_data.get('task_params') or '{}'
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(_("task_params 必须是合法 JSON: %(exc)s") % {'exc': exc})

        if not isinstance(parsed, dict):
            raise forms.ValidationError(_("task_params 必须是 JSON 对象（键值对）。"))
        return parsed

    def clean(self):
        cleaned_data = super().clean()
        plan_type = cleaned_data.get('plan_type')
        if plan_type == 'interval' and not cleaned_data.get('interval_period'):
            self.add_error('interval_period', _('interval 类型必须选择间隔单位。'))
        if plan_type == 'period' and not cleaned_data.get('period_type'):
            self.add_error('period_type', _('period 类型必须选择周期单位。'))
        if plan_type == 'specdate' and not cleaned_data.get('spec_date'):
            self.add_error('spec_date', _('specdate 类型必须填写执行时间。'))
        return cleaned_data


class TaskExecutionLogForm(forms.ModelForm):
    class Meta:
        model = TaskExecutionLog
        fields = ['status', 'error_message', 'result_summary']
        widgets = {
            'error_message': forms.Textarea(attrs={'rows': 4}),
            'result_summary': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_class = 'w-full rounded border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'
        for field in self.fields.values():
            field.widget.attrs['class'] = base_class


class SystemPromptForm(forms.ModelForm):
    class Meta:
        model = SystemPrompt
        fields = ['role_name', 'role_definition', 'prompt_content', 'purpose', 'is_active', 'is_default']
        widgets = {
            'role_definition': forms.Textarea(attrs={'rows': 3}),
            'prompt_content': forms.Textarea(attrs={'rows': 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_class = 'w-full rounded border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'
        checkbox_class = 'h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500'
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = checkbox_class
            else:
                widget.attrs['class'] = base_class


def _build_task_meta() -> dict:
    system_params = {'db_id'}
    configured = getattr(settings, 'TASK_SYSTEM_PARAM_NAMES', None)
    if configured:
        system_params.update({str(name).strip().lower() for name in configured if str(name).strip()})

    meta = {}
    for task_name, task_label in task_list():
        full_schema = task_param_schema(task_name)
        filtered_schema = [
            param for param in full_schema
            if str(param.get('name', '')).strip().lower() not in system_params
        ]
        template = task_param_template(task_name)
        filtered_template = {
            key: value
            for key, value in template.items()
            if str(key).strip().lower() not in system_params
        }
        meta[task_name] = {
            'label': task_label,
            'schema': filtered_schema,
            'template': filtered_template,
        }
    return meta


def _save_task_and_attachments(form: CustomTaskCreateForm, request, creator=None, instance=None):
    obj = form.save(commit=False)
    if creator is not None:
        obj.creator = creator
    elif instance is not None:
        obj.creator = instance.creator

    obj.save()
    uploaded_files = request.FILES.getlist('attachments')
    for uploaded in uploaded_files:
        TaskAttachment.objects.create(
            task=obj,
            file=uploaded,
            filename=getattr(uploaded, 'name', '') or '',
        )
    if uploaded_files:
        obj.save()
    return obj


def _get_task_for_user(user, task_id):
    queryset = UserScheduledTask.objects.all()
    if not user.is_staff:
        queryset = queryset.filter(creator=user)
    return get_object_or_404(queryset, pk=task_id)


def _conversation_qs_for_user(user):
    qs = AIChatConversation.objects.all()
    if not user.is_staff:
        qs = qs.filter(user=user)
    return qs


def _message_for_user(user, message_id):
    qs = AIChatMessage.objects.select_related('conversation')
    if not user.is_staff:
        qs = qs.filter(conversation__user=user)
    return get_object_or_404(qs, pk=message_id)


def _refresh_conversation_stats(conversation: AIChatConversation):
    msgs = conversation.messages.order_by('created_at')
    count = msgs.count()
    last_msg = msgs.last()
    conversation.message_count = count
    conversation.last_message_at = last_msg.created_at if last_msg else None
    conversation.last_role = last_msg.role if last_msg else ''
    conversation.last_text = last_msg.text if last_msg else ''
    conversation.save(update_fields=['message_count', 'last_message_at', 'last_role', 'last_text', 'updated_at'])


def _extract_keywords(text_list: list) -> str:
    """Extract keywords using jieba TF-IDF for Chinese/English mixed text."""
    text = " ".join([str(t) for t in text_list if t])
    if not text.strip():
        return ""

    try:
        import jieba.analyse
        # extract_tags uses TF-IDF algorithm
        # topK=5: return top 5 keywords
        # allowPOS: filter by parts of speech (noun, place, verb-noun, verb, english)
        tags = jieba.analyse.extract_tags(text, topK=5, allowPOS=('n', 'ns', 'vn', 'v', 'eng'))
        if tags:
            return ",".join(tags)
    except ImportError:
        pass

    # Fallback to simple regex if jieba is missing or returns nothing
    words = re.findall(r'\w+', text)
    common = Counter(words).most_common(5)
    return ",".join([w[0] for w in common])


def _build_chat_memory(conversation, keywords):
    """Update conversation chat_memory based on new keywords/context."""
    # 示例实现：将关键词追加到 memory 中
    if not keywords:
        return
    
    current_mem = conversation.chat_memory or []
    if not isinstance(current_mem, list):
        current_mem = []
    
    # 简单的去重添加
    existing_keys = set()
    for item in current_mem:
        if isinstance(item, dict) and 'keywords' in item:
             existing_keys.add(item['keywords'])
    
    if keywords not in existing_keys:
        current_mem.append({
            'timestamp': timezone.now().isoformat(),
            'keywords': keywords,
            'summary': 'Automatic extraction'
        })
        # 保持记忆不过长
        if len(current_mem) > 10:
            current_mem = current_mem[-10:]
            
    conversation.chat_memory = current_mem


def _mode_default_system_prompt(mode_code: str):
    """Return the active default SystemPrompt for a conversation mode if set."""
    try:
        mode_obj = (
            ConversationMode.objects
            .filter(code=mode_code, is_active=True)
            .select_related('default_system_prompt')
            .first()
        )
        if mode_obj and mode_obj.default_system_prompt and mode_obj.default_system_prompt.is_active:
            return mode_obj.default_system_prompt
    except Exception:
        pass
    return None


def _save_uploaded_documents(files):
    """Persist uploaded files and return list of objects exposing file.path for Gemini."""
    documents = []
    for f in files:
        try:
            filename = f"reference_docs/chat/{uuid.uuid4()}_{f.name}"
            saved_path = default_storage.save(filename, f)
            # default_storage.path may raise if not filesystem based
            abs_path = default_storage.path(saved_path)
            documents.append(SimpleNamespace(file=SimpleNamespace(path=abs_path)))
        except Exception:
            continue
    return documents


def _prompt_to_text(prompt_obj: SystemPrompt = None):
    if not prompt_obj:
        return None
    return "\n".join([
        f"角色：{prompt_obj.role_name}",
        f"角色定义：{prompt_obj.role_definition}",
        f"提示词：{prompt_obj.prompt_content}",
    ])

def update_user_language(request):
    if request.method == 'POST':
        lang_code = request.POST.get('language')
        if lang_code in [lang[0] for lang in settings.LANGUAGES]:
            # 1. 更新当前 Session 语言
            translation.activate(lang_code)
            request.session[translation.LANGUAGE_SESSION_KEY] = lang_code
            
            # 2. 如果用户已登录，保存到数据库
            if request.user.is_authenticated:
                profile, created = UserProfile.objects.get_or_create(user=request.user)
                profile.language = lang_code
                profile.save()
                
    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def system_prompt_list(request):
    if not request.user.is_staff:
        return HttpResponseForbidden(_("仅管理员可维护系统提示词。"))

    editing_id = request.GET.get('id')
    editing_obj = SystemPrompt.objects.filter(pk=editing_id).first() if editing_id else None

    if request.method == 'POST':
        target_id = request.POST.get('prompt_id') or None
        instance = SystemPrompt.objects.filter(pk=target_id).first() if target_id else None
        form = SystemPromptForm(request.POST, instance=instance)
        if form.is_valid():
            prompt = form.save()
            messages.success(request, _("系统提示词“%(name)s”已保存。") % {'name': prompt.role_name})
            return redirect('api_services:system_prompt_list')
    else:
        form = SystemPromptForm(instance=editing_obj)

    prompts = SystemPrompt.objects.order_by('-updated_at')
    return render(request, 'system_prompts.html', {
        'form': form,
        'prompts': prompts,
        'editing': editing_obj,
        'page_title': _('系统提示词库'),
    })


@login_required
@require_POST
def system_prompt_delete(request, prompt_id: int):
    if not request.user.is_staff:
        return HttpResponseForbidden(_("仅管理员可维护系统提示词。"))

    prompt = get_object_or_404(SystemPrompt, pk=prompt_id)
    prompt.delete()
    messages.success(request, _("系统提示词“%(name)s”已删除。") % {'name': prompt.role_name})
    return redirect('api_services:system_prompt_list')


@login_required
def custom_task_create_view(request):
    task_meta = _build_task_meta()
    initial = {
        'plan_type': 'interval',
        'interval': 1,
        'interval_period': 'Minutes',
        'is_active': True,
        'task_params': '{}',
    }

    if request.method == 'POST':
        form = CustomTaskCreateForm(request.POST, request.FILES)
        if form.is_valid():
            obj = _save_task_and_attachments(form, request, creator=request.user)
            messages.success(request, _("任务“%(title)s”创建成功。") % {'title': obj.title})
            return redirect('api_services:task_manage')
    else:
        form = CustomTaskCreateForm(initial=initial)

    return render(request, 'tasks_create.html', {
        'form': form,
        'task_meta': task_meta,
        'page_title': _('创建自定义任务'),
        'submit_label': _('保存任务'),
        'back_url': 'api_services:task_manage',
    })


@login_required
def custom_task_edit_view(request, task_id: int):
    task = _get_task_for_user(request.user, task_id)
    task_meta = _build_task_meta()

    if request.method == 'POST':
        form = CustomTaskCreateForm(request.POST, request.FILES, instance=task)
        if form.is_valid():
            obj = _save_task_and_attachments(form, request, instance=task)
            messages.success(request, _("任务“%(title)s”更新成功。") % {'title': obj.title})
            return redirect('api_services:task_manage')
    else:
        form = CustomTaskCreateForm(instance=task, initial={'task_params': json.dumps(task.task_params or {}, ensure_ascii=False)})

    return render(request, 'tasks_create.html', {
        'form': form,
        'task_meta': task_meta,
        'page_title': _('编辑任务：%(title)s') % {'title': task.title},
        'submit_label': _('保存修改'),
        'back_url': 'api_services:task_manage',
        'existing_attachments': task.attachments.all(),
    })


@login_required
def task_log_edit_view(request, log_id: int):
    log = get_object_or_404(TaskExecutionLog, pk=log_id)
    if request.method == 'POST':
        form = TaskExecutionLogForm(request.POST, instance=log)
        if form.is_valid():
            form.save()
            messages.success(request, _('执行记录已更新。'))
            return redirect('api_services:task_manage')
    else:
        form = TaskExecutionLogForm(instance=log)

    return render(request, 'task_log_edit.html', {'form': form, 'log': log})


@login_required
def ai_workbench_view(request):
    conversation_modes = ConversationMode.objects.filter(is_active=True).order_by('code')
    prompts = SystemPrompt.objects.filter(is_active=True).order_by('role_name')
    mode_defaults = {}
    mode_list = []
    
    # 获取所有注册技能
    skill_list = list(skill_registry.functions_dict.keys())
    skill_list.sort()

    for mode in conversation_modes:
        p = _mode_default_system_prompt(mode.code)
        mode_defaults[mode.code] = {
            'id': p.id if p else None,
            'name': p.role_name if p else '',
            'content': p.prompt_content if p else '',
        }
        mode_list.append({
            'code': mode.code,
            'label': mode.label,
            'description': mode.description,
        })
    
    conversation_mode_default = conversation_modes.first().code if conversation_modes.exists() else 'run_intelligent_task'

    data = {
        'page_title': _('AI Builder 对话工作台'),
        'skill_list': skill_list,
        'system_prompts_json': json.dumps([
            {'id': prompt.id, 'name': prompt.role_name}
            for prompt in prompts
        ], ensure_ascii=False),
        'mode_defaults_json': json.dumps(mode_defaults, ensure_ascii=False),
        'modes_json': json.dumps(mode_list, ensure_ascii=False),
        'conversation_modes': conversation_modes,
        'conversation_mode_default': conversation_mode_default,
    }
    return render(request, 'ai_workbench.html', data)


@login_required
def skill_details(request):
    """API to fetch details of a specific skill."""
    skill_name = request.GET.get('skill_name')
    if not skill_name:
         return ApiResponse.fail(_("Missing skill_name parameter"), code=400)
    
    details = skill_registry.get_skill_details(skill_name)
    if not details:
        return ApiResponse.fail(_("Skill not found"), code=404)
        
    return ApiResponse.success(details)


def ai_workbench_chat(request):
    try:
        if request.content_type == 'application/json':
            payload = json.loads(request.body or '{}')
        else:
            payload = request.POST
    except Exception:
        payload = {}

    uploaded_files = request.FILES.getlist('documents') if hasattr(request, 'FILES') else []
    documents = _save_uploaded_documents(uploaded_files) if uploaded_files else []

    conversation_id = payload.get('conversation_id') or None
    user_message = str(payload.get('message', '')).strip()
    history = payload.get('history') or payload.get('history_json') or []
    if isinstance(history, str):
        try:
            history = json.loads(history)
        except Exception:
            history = []
    conversation_mode = str(payload.get('mode') or 'run_intelligent_task').strip() or 'run_intelligent_task'
    allowed_modes = set(ConversationMode.objects.filter(is_active=True).values_list('code', flat=True))
    if conversation_mode not in allowed_modes:
        conversation_mode = 'get_content'

    payload_system_prompt_id = payload.get('system_prompt_id') or None
    payload_system_prompt_name = payload.get('system_prompt_name') or None
    sys_config_override = payload.get('sys_config') or None

    if not user_message:
        return ApiResponse.fail(message='message_required', code=400, status=400)

    history_lines = []
    for item in history[-6:]:
        role = str(item.get('role', 'user')).upper()
        text = str(item.get('text', ''))
        history_lines.append(f"{role}: {text}")
    history_text = "\n".join(history_lines)

    # 解析系统提示：优先用户提供，其次模式默认，再次全局默认
    sys_prompt_obj = None
    sys_prompt_text = None
    legacy_sys_prompt = _(
        "你是工作流助手，可以通过函数工具完成动作。"
        "优先选择工具而不是直接回答。"
        "创建 Python 技能时，调用 create_and_register_skill(description)。"
        "创建用户定时任务时，调用 create_user_task(...)；在调用前先从用户请求中提取并列出任务需求、执行时间或间隔(plan_type/interval/interval_period/period_type/spec_date)、是否循环(is_recurring)、启用状态(is_active)、调用函数(task_name)和参数(task_params JSON)。"
        "如果必需字段缺失（如任务名称、计划/时间、task_name、task_params、skill_name），先向用户询问补全后再调用。"
        "如果 task_name=api_services.tasks.run_skill_task，则 task_params 必须包含 skill_name（目标技能函数名）以及可选 skill_kwargs（JSON 对象参数）。"
        "如用户提到附件/文件但页面未提供上传入口，请提示无法直接上传，需用户提供可访问的链接或路径。"
        "保持简洁回复，工具创建成功后给出结果摘要。"
    )

    mode_default_prompt = _mode_default_system_prompt(conversation_mode)
    global_default_prompt = SystemPrompt.objects.filter(is_active=True, is_default=True).first()
    resolved_prompt_id = None
    resolved_prompt_name = None

    if conversation_mode == 'get_content':
        # get_content 可以接受用户指定的系统提示，否则落到模式默认
        if payload_system_prompt_id:
            sys_prompt_obj = SystemPrompt.objects.filter(pk=payload_system_prompt_id, is_active=True).first()
        elif payload_system_prompt_name:
            sys_prompt_obj = SystemPrompt.objects.filter(role_name=payload_system_prompt_name, is_active=True).first()

        if not sys_prompt_obj and not sys_config_override:
            sys_prompt_obj = mode_default_prompt or global_default_prompt

        if sys_config_override:
            sys_prompt_text = sys_config_override
            resolved_prompt_id = None
            resolved_prompt_name = None
        else:
            sys_prompt_text = _prompt_to_text(sys_prompt_obj)
            resolved_prompt_id = getattr(sys_prompt_obj, 'id', None) or payload_system_prompt_id
            resolved_prompt_name = getattr(sys_prompt_obj, 'role_name', None) or payload_system_prompt_name
    else:
        sys_prompt_obj = mode_default_prompt or global_default_prompt
        sys_prompt_text = _prompt_to_text(sys_prompt_obj) or legacy_sys_prompt

    if history_text:
        prompt = f"历史对话:\n{history_text}\nUSER: {user_message}\n请继续。"
    else:
        prompt = user_message

    # Determine model purpose from system prompt
    current_model_purpose = 'general'
    if sys_prompt_obj and getattr(sys_prompt_obj, 'purpose', None):
        current_model_purpose = sys_prompt_obj.purpose

    stream = str(payload.get('stream') or request.GET.get('stream') or '').lower() in {'1', 'true', 'yes'}

    def persist_conversation(reply_text, reply_logs, system_prompt_obj=None):
        cid_local = None
        if conversation_id:
            try:
                cid_local = uuid.UUID(str(conversation_id))
            except Exception:
                reply_logs.append(f"Invalid conversation_id provided: {conversation_id}, generating a new one.")

        try:
            if cid_local:
                conversation, _ = AIChatConversation.objects.get_or_create(
                    id=cid_local,
                    defaults={
                        'user': request.user,
                        'title': user_message[:50],
                        'conversation_mode': conversation_mode,
                    },
                )
            else:
                conversation = AIChatConversation.objects.create(
                    user=request.user,
                    title=user_message[:50],
                    conversation_mode=conversation_mode,
                )
                cid_local = conversation.id

            if conversation.conversation_mode != conversation_mode:
                conversation.conversation_mode = conversation_mode

            AIChatMessage.objects.create(
                conversation=conversation,
                user=request.user,
                role='user',
                text=user_message,
                system_prompt=sys_prompt_obj,
            )
            AIChatMessage.objects.create(
                conversation=conversation,
                user=request.user,
                role='assistant',
                text=str(reply_text or ''),
                system_prompt=sys_prompt_obj,
            )

            if not conversation.title:
                conversation.title = user_message[:50]
            _refresh_conversation_stats(conversation)
            conversation.save(update_fields=['title', 'conversation_mode'])

            try:
                keywords = _extract_keywords([conversation.last_text, user_message, str(reply_text or '')])
                _build_chat_memory(conversation, keywords)
                conversation.save(update_fields=['chat_memory', 'key_words', 'updated_at'])
            except Exception as mem_err:
                reply_logs.append(f"Memory update failed: {mem_err}")
        except Exception as e:
            reply_logs.append(f"Failed to persist chat messages: {e}")
        return {
            'conversation_id': cid_local,
            'system_prompt_id': getattr(system_prompt_obj, 'id', None),
            'system_prompt_name': getattr(system_prompt_obj, 'role_name', None),
        }

    # Streaming for run_intelligent_task AND skill_call
    if (conversation_mode == 'run_intelligent_task' or conversation_mode == 'skill_call') and stream:
        q = SimpleQueue()
        stop = object()

        def on_log(msg: str):
            q.put({'type': 'log', 'message': msg})

        def worker():
            reply_logs_local = []
            ai_reply = None
            try:
                if conversation_mode == 'skill_call':
                    skill_name = str(payload.get('skill_name') or '').strip()
                    if not skill_name:
                         # 抛出异常或直接返回错误消息给前端
                         q.put({'type': 'error', 'message': 'skill_name_required_for_skill_call'})
                         return

                    ai_reply = skill_call(
                        skill_name=skill_name,
                        context=prompt,
                        sys_config=sys_prompt_text,
                        conversation_mode=conversation_mode,
                        documents=documents,
                        debug=True,
                        on_log=on_log,
                        purpose=current_model_purpose
                    )
                else:
                    # run_intelligent_task
                    ai_reply = run_intelligent_task(
                        prompt,
                        sys_config=sys_prompt_text,
                        max_turns=6,
                        current_user=request.user,
                        debug=True,
                        on_log=on_log,
                        conversation_mode=conversation_mode,
                        documents=documents,
                        purpose=current_model_purpose
                    )
                
                reply_text_local = ai_reply.get('text') if isinstance(ai_reply, dict) else ai_reply
                reply_logs_local.extend(ai_reply.get('logs', []) if isinstance(ai_reply, dict) else [])
                meta = persist_conversation(reply_text_local, reply_logs_local, sys_prompt_obj)
                cid_local = meta.get('conversation_id')
                q.put({
                    'type': 'reply',
                    'reply': reply_text_local,
                    'conversation_id': str(cid_local) if cid_local else '',
                    'logs': reply_logs_local,
                    'system_prompt_id': meta.get('system_prompt_id'),
                    'system_prompt_name': meta.get('system_prompt_name'),
                })
            except Exception as exc:
                q.put({'type': 'error', 'message': str(exc)})
            finally:
                q.put(stop)

        threading.Thread(target=worker, daemon=True).start()

        def stream_response():
            import json as _json
            while True:
                item = q.get()
                if item is stop:
                    break
                yield _json.dumps(item, ensure_ascii=False) + "\n"

        return StreamingHttpResponse(stream_response(), content_type='application/x-ndjson')

    reply_logs = []
    reply_text = ""

    if conversation_mode == 'run_intelligent_task':
        ai_reply = run_intelligent_task(
            prompt,
            sys_config=sys_prompt_text,
            max_turns=6,
            current_user=request.user,
            debug=True,
            conversation_mode=conversation_mode,
            documents=documents,
            purpose=current_model_purpose
        )
        reply_text = ai_reply.get('text') if isinstance(ai_reply, dict) else ai_reply
        reply_logs = ai_reply.get('logs', []) if isinstance(ai_reply, dict) else []

    elif conversation_mode == 'skill_call':
        skill_name = str(payload.get('skill_name') or '').strip()
        if not skill_name:
            return ApiResponse.fail(message='skill_name_required_for_skill_call', code=400, status=400)
        try:
            ai_reply = skill_call(
                skill_name=skill_name,
                context=prompt,
                sys_config=sys_prompt_text,
                conversation_mode=conversation_mode,
                documents=documents,
                debug=True,
                purpose=current_model_purpose
            )
            reply_text = ai_reply.get('text') if isinstance(ai_reply, dict) else ai_reply
            reply_logs = ai_reply.get('logs', []) if isinstance(ai_reply, dict) else []
        except Exception as exc:
            reply_text = f"技能调用失败: {exc}"
            reply_logs.append(str(exc))

    elif conversation_mode == 'get_content':
        try:
            reply_text = get_content(
                prompt,
                sys_config=sys_prompt_text,
                system_prompt_id=resolved_prompt_id,
                system_prompt_name=resolved_prompt_name,
                conversation_mode=conversation_mode,
                documents=documents,
                purpose=current_model_purpose
            )
        except Exception as exc:
            reply_text = f"内容生成失败: {exc}"
            reply_logs.append(str(exc))

    meta = persist_conversation(reply_text, reply_logs, sys_prompt_obj) or {}
    cid = meta.get('conversation_id')

    return ApiResponse.success(data={
        'reply': reply_text,
        'conversation_id': str(cid) if cid else None,
        'logs': reply_logs,
        'mode': conversation_mode,
        'system_prompt_id': meta.get('system_prompt_id'),
        'system_prompt_name': meta.get('system_prompt_name'),
    })


@login_required
def ai_workbench_history(request):
    cid = request.GET.get('conversation_id')
    if not cid:
        qs = _conversation_qs_for_user(request.user).order_by('-updated_at')
        convs = [
            {
                'id': str(c.id),
                'title': c.title or _('未命名会话'),
                'conversation_mode': c.conversation_mode,
                'message_count': c.message_count,
                'last_message_at': c.last_message_at.isoformat() if c.last_message_at else None,
                'last_text': c.last_text[:120] if c.last_text else '',
            }
            for c in qs[:50]
        ]
        return ApiResponse.success(data={'conversations': convs})

    try:
        conversation = _conversation_qs_for_user(request.user).get(id=cid)
        msgs = conversation.messages.order_by('created_at')
        data = [
            {
                'id': m.id,
                'role': m.role,
                'text': m.text,
                'created_at': m.created_at.isoformat(),
                'system_prompt_id': m.system_prompt_id,
                'system_prompt_name': m.system_prompt.role_name if m.system_prompt else None,
            }
            for m in msgs
        ]
        return ApiResponse.success(data={
            'conversation_id': str(conversation.id),
            'title': conversation.title,
            'conversation_mode': conversation.conversation_mode,
            'messages': data,
        })
    except Exception as e:
        return ApiResponse.fail(message=str(e), data={'messages': []}, code=400, status=400)


@login_required
@require_POST
def ai_workbench_conversation_update(request):
    """Update AIChatConversation fields (currently title / mode)."""
    try:
        payload = json.loads(request.body or '{}') if request.content_type == 'application/json' else request.POST
    except Exception:
        payload = {}

    conv_id = payload.get('conversation_id') or payload.get('id')
    if not conv_id:
        return ApiResponse.fail(message='conversation_id_required', code=400, status=400)

    try:
        conversation = _conversation_qs_for_user(request.user).get(id=conv_id)
    except Exception as exc:
        return ApiResponse.fail(message=str(exc), code=404, status=404)

    updates = {}
    title = payload.get('title')
    if title is not None:
        updates['title'] = str(title).strip()

    mode = payload.get('conversation_mode') or payload.get('mode')
    if mode is not None:
        valid_modes = set(dict(AIChatConversation._meta.get_field('conversation_mode').choices).keys())
        if mode in valid_modes:
            updates['conversation_mode'] = mode
        else:
            return ApiResponse.fail(message='invalid_conversation_mode', code=400, status=400)

    if not updates:
        return ApiResponse.fail(message='no_fields_to_update', code=400, status=400)

    for field, value in updates.items():
        setattr(conversation, field, value)

    update_fields = list(updates.keys()) + ['updated_at']
    conversation.save(update_fields=update_fields)

    return ApiResponse.success(data={
        'conversation': {
            'id': str(conversation.id),
            'title': conversation.title or _('未命名会话'),
            'conversation_mode': conversation.conversation_mode,
            'message_count': conversation.message_count,
            'last_message_at': conversation.last_message_at.isoformat() if conversation.last_message_at else None,
            'last_text': conversation.last_text[:120] if conversation.last_text else '',
        }
    }, message='updated')


@login_required
@require_POST
def ai_workbench_conversation_delete(request):
    try:
        payload = json.loads(request.body or '{}') if request.content_type == 'application/json' else request.POST
    except Exception:
        payload = {}

    conv_id = payload.get('conversation_id') or payload.get('id')
    if not conv_id:
        return ApiResponse.fail(message='conversation_id_required', code=400, status=400)

    try:
        conversation = _conversation_qs_for_user(request.user).get(id=conv_id)
    except Exception as exc:
        return ApiResponse.fail(message=str(exc), code=404, status=404)

    conversation.delete()
    return ApiResponse.success(data={'conversation_id': str(conv_id)}, message='deleted')


@login_required
def ai_workbench_conversation_edit(request, cid):
    conversation = get_object_or_404(_conversation_qs_for_user(request.user), id=cid)
    choices = AIChatConversation._meta.get_field('conversation_mode').choices
    users = User.objects.all().order_by('username') if request.user.is_staff else User.objects.filter(id=conversation.user_id)
    error = None
    saved = False

    if request.method == 'POST':
        data = request.POST
        conversation.title = data.get('title') or ''
        mode = data.get('conversation_mode') or conversation.conversation_mode
        if mode in dict(choices):
            conversation.conversation_mode = mode

        if request.user.is_staff:
            user_id = data.get('user')
            try:
                conversation.user = User.objects.get(id=user_id) if user_id else None
            except Exception:
                pass

        conversation.last_role = data.get('last_role') or ''
        conversation.last_text = data.get('last_text') or ''
        conversation.key_words = data.get('key_words') or ''

        msg_count_raw = data.get('message_count')
        try:
            conversation.message_count = int(msg_count_raw) if msg_count_raw is not None else conversation.message_count
        except Exception:
            error = _('message_count 需要是数字')

        lm_at_raw = data.get('last_message_at')
        if lm_at_raw:
            try:
                dt = datetime.fromisoformat(lm_at_raw)
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                conversation.last_message_at = dt
            except Exception:
                error = _('last_message_at 需要 ISO8601 日期时间')
        else:
            conversation.last_message_at = None

        mem_raw = data.get('chat_memory') or '[]'
        try:
            conversation.chat_memory = json.loads(mem_raw)
        except Exception as exc:
            error = _('chat_memory 需要合法 JSON: %(exc)s') % {'exc': exc}

        if not error:
            conversation.save()
            saved = True

    chat_memory_text = json.dumps(conversation.chat_memory, ensure_ascii=False, indent=2)
    messages_qs = conversation.messages.all().order_by('created_at')

    return render(request, 'ai_conversation_edit.html', {
        'conversation': conversation,
        'conversation_mode_choices': choices,
        'users': users,
        'chat_memory_text': chat_memory_text,
        'error': error,
        'saved': saved,
        'messages': messages_qs,
    })


@login_required
def task_manage_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete_task':
            task_id = request.POST.get('task_id')
            task = _get_task_for_user(request.user, task_id)
            title = task.title
            task.delete()
            messages.success(request, _("任务“%(title)s”已删除。") % {'title': title})
            return redirect('api_services:task_manage')

        if action == 'delete_log':
            log_id = request.POST.get('log_id')
            log = get_object_or_404(TaskExecutionLog, pk=log_id)
            log.delete()
            messages.success(request, _('执行记录已删除。'))
            return redirect('api_services:task_manage')

        if action == 'run_now':
            task_id = request.POST.get('task_id')
            task = _get_task_for_user(request.user, task_id)
            try:
                payload = task.task_params or {}
                if not isinstance(payload, dict):
                    payload = {}
                payload = dict(payload)
                payload.setdefault('db_id', task.id)

                async_result = current_app.send_task(task.task_name, kwargs=payload)
                messages.success(request, _("任务“%(title)s”已触发执行 (task_id=%(tid)s).") % {'title': task.title, 'tid': async_result.id})
            except Exception as e:
                messages.error(request, _("任务“%(title)s”触发失败: %(err)s") % {'title': task.title, 'err': e})
            return redirect('api_services:task_manage')

    task_queryset = UserScheduledTask.objects.select_related('creator', 'periodic_task').prefetch_related('attachments').order_by('-updated_at')
    if not request.user.is_staff:
        task_queryset = task_queryset.filter(creator=request.user)

    if request.user.is_staff:
        logs = TaskExecutionLog.objects.order_by('-timestamp')[:100]
    else:
        logs = TaskExecutionLog.objects.filter(task__creator=request.user).order_by('-timestamp')[:100]

    return render(request, 'tasks_manage.html', {
        'tasks': task_queryset,
        'logs': logs,
    })


class AIChatMessageListView(LoginRequiredMixin, ListView):
    model = AIChatMessage
    template_name = 'ai_chat_message_list.html'
    context_object_name = 'messages'
    paginate_by = 20
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.GET.get('q')
        print("Search query:", q)
        if q:
            from django.db.models import Q
            queryset = queryset.filter(Q(conversation_id=q))
        return queryset


@login_required
@require_POST
def ai_chat_message_update(request, pk):
    try:
        payload = json.loads(request.body or '{}') if request.content_type == 'application/json' else request.POST
    except Exception:
        payload = {}

    message = get_object_or_404(AIChatMessage, pk=pk)
    
    # Check permissions if not staff, assuming only their own messages?
    # For now, just allow simple update as before
    role = payload.get('role')
    text = payload.get('text')
    
    if role:
        message.role = role
    if text is not None:
        message.text = text
        
    try:
        message.save(update_fields=['role', 'text'])
        # Optionally refresh stats here like before:
        if message.conversation:
            _refresh_conversation_stats(message.conversation)
        return ApiResponse.success(data={'id': message.id, 'role': message.role, 'text': message.text}, message='updated')
    except Exception as e:
        return ApiResponse.fail(message=str(e), code=400, status=400)


@login_required
@require_POST
def ai_chat_message_delete(request, pk):
    message = get_object_or_404(AIChatMessage, pk=pk)
    try:
        conversation = message.conversation
        message.delete()
        if conversation:
            _refresh_conversation_stats(conversation)
        return ApiResponse.success(data={'id': pk}, message='deleted')
    except Exception as e:
        return ApiResponse.fail(message=str(e), code=400, status=400)
