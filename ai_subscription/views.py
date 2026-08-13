from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, HttpResponse
from django.http import JsonResponse, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from .models import Subscription, ReferenceDocument, ReportHistory, SubscriptionRecipient
import os, json
from datetime import datetime
from django.urls import reverse_lazy
from django.views.generic import ListView
from django.views.generic.edit import UpdateView, DeleteView
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, redirect
from .services import *
from .tasks import task_generate_ai_report # 导入你定义的异步任务
from django.db import transaction

@login_required
def dashboard(request):
    # 只能看到自己创建的订阅任务
    my_tasks = Subscription.objects.filter(creator=request.user).prefetch_related('recipient_list')
    return render(request, 'dashboard.html', {'tasks': my_tasks})

@login_required
def create_task(request):
    if request.method == "POST":
        # 1. 创建订阅主表
        task = Subscription.objects.create(
            creator=request.user,  # 强制绑定当前登录用户
            report_title=request.POST.get('title'),
            keywords=request.POST.get('keywords')
        )
        # 2. 解析多邮箱并存入接收者表
        emails = request.POST.get('emails').split(',') # 假设前端用逗号分隔
        for email in emails:
            SubscriptionRecipient.objects.create(
                subscription=task,
                email=email.strip()
            )
        return redirect('dashboard')

# 订阅列表视图
class SubscriptionListView(LoginRequiredMixin,ListView):
    model = Subscription
    template_name = 'subs_manage.html'
    context_object_name = 'subscriptions' # 模板中使用的变量名
    def get_queryset(self):
        # 此时 self.request.user 是可用的
        print(f"当前查询用户: {self.request.user}")
        # 过滤属于当前用户的订阅，并按主键倒序排列
        return Subscription.objects.filter(creator=self.request.user).order_by('-pk')

# 更新视图
class SubscriptionUpdateView(UpdateView):
    model = Subscription
    # 允许用户编辑的字段
    fields = ['report_title', 'keywords', 'description', 'period','subscription_date', 'send_time', 'format_type','is_active']
    template_name = 'subscription_update.html'
    # 更新成功后跳转回列表页
    success_url = reverse_lazy('ai_subscription:subs_manage')

    @transaction.atomic # 建议加上事务，确保主表、从表、文件同步成功
    def form_valid(self, form):
        # 1. 保存 Subscription 主表字段的更新
        self.object = form.save()

        # 2. 【核心逻辑】：更新多接收人邮件列表
        emails = self.request.POST.getlist('recipient_emails[]')
        if emails:
            # 策略：先清理该任务旧的接收人，再批量添加新的
            self.object.recipient_list.all().delete() # 这里的 recipient_list 是你在 models 中定义的 related_name
            new_recipients = [
                SubscriptionRecipient(subscription=self.object, email=email.strip())
                for email in set(emails) if email.strip()
            ]
            SubscriptionRecipient.objects.bulk_create(new_recipients)

        # 3. 处理可能追加的文件上传
        files = self.request.FILES.getlist('attachments')
        for f in files:
            ReferenceDocument.objects.create(subscription=self.object, file=f)

        messages.success(self.request, "配置及邮件列表已成功更新！")
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        # 核心调试步骤：如果更新失败，控制台会打印具体哪个字段出错了
        print("提交的时间原始值:", self.request.POST.get('send_time'))
        print("表单校验失败！错误信息：", form.errors)
        messages.error(self.request, "更新失败，请检查输入内容:" + str(form.errors))
        return super().form_invalid(form)
    
    def get_queryset(self):
            """防止越权访问：只能修改自己创建的任务"""
            return super().get_queryset().filter(creator=self.request.user)

# 删除视图
class SubscriptionDeleteView(DeleteView):
    model = Subscription
    # 删除成功后跳转到管理列表页
    success_url = reverse_lazy('ai_subscription:subs_manage')
    # 默认寻找名为 subscription_cancel.html 的模板
    template_name = 'subscription_cancel.html'

    def form_valid(self, form):
        # 1. 获取成功后的跳转地址
        success_url = self.get_success_url()
        
        # 2. 执行逻辑操作（如发送通知、记录日志）
        # 注意：这里我们不需要手动调 self.object.delete()
        # 因为在 Django 4.x/5.x 中，DeleteView 的 form_valid 会自动处理删除
        messages.success(self.request, f"已成功取消订阅！")
        
        # 3. 直接执行父类的删除流程
        # 这会自动处理数据库删除并跳转到 success_url
        return super().form_valid(form)


    def get_queryset(self):
        """安全保护：确保用户只能删除自己的数据"""
        return super().get_queryset().filter(creator=self.request.user)
    
    
# Create your views here.
def manage_recipients(request, sub_id):
    # 越权防护：通过双重过滤确保该 sub_id 确实属于当前登录用户
    sub = get_object_or_404(Subscription, id=sub_id, creator=request.user)
    
    # 获取属于该订阅的邮件列表
    recipients = sub.recipient_list.all()
    
    return render(request, 'recipients.html', {
        'subscription': sub,
        'recipients': recipients
    })

def report_history_list(request, sub_id):
    """展示某个订阅的所有历史简报列表"""
    subscription = get_object_or_404(Subscription, id=sub_id, creator=request.user)
    histories = subscription.histories.all()
    
    return render(request, 'report_history_list.html', {
        'subscription': subscription,
        'histories': histories
    })

def report_detail(request, report_id):
    """查看单篇简报的详细内容"""
    report = get_object_or_404(ReportHistory, id=report_id, subscription__creator=request.user)
    return render(request, 'report_detail.html', {
        'report': report
    })

def subs_ai(request):
    rendered_page = render(request, 'AI_subscription.html')
    return HttpResponse(rendered_page)

def subs_manage(request):
    rendered_page = render(request, 'subs_manage.html')
    return HttpResponse(rendered_page)

@login_required # 确保只有登录用户能调用，用于获取 request.user
def subscribe_api(request):
    if request.method == 'POST':
        try:
            # --- 修改部分 1: 时间转换 ---
            raw_time = request.POST.get('send_time')
            processed_time = datetime.strptime(raw_time, '%H:%M').time() if raw_time else None            
            # 使用事务保证主表、子表和文件要么全部成功，要么全部失败
            with transaction.atomic():
                # 1. 保存订阅主体
                # 注意：我们移除了原有的 user_email 和 user_name 字段（改为由 creator 和接收者表处理）
                sub = Subscription.objects.create(
                    creator=request.user,           # 绑定当前登录的创建者
                    report_title=request.POST.get('report_title'),
                    keywords=request.POST.get('keywords'),
                    description=request.POST.get('description'),
                    period=request.POST.get('period'),
                    send_time=processed_time,
                    format_type=request.POST.get('format'),
                    is_active=request.POST.get('is_active') == 'on'  # 获取开关状态
                )

                # 2. 保存多接收人邮件列表
                emails = request.POST.getlist('recipient_emails[]')
                recipient_objs = [
                    SubscriptionRecipient(subscription=sub, email=email.strip())
                    for email in set(emails) if email.strip() # 去重并过滤空值
                ]
                if recipient_objs:
                    SubscriptionRecipient.objects.bulk_create(recipient_objs)

                # 3. 保存关联文件 (ReferenceDocument)
                files = request.FILES.getlist('attachments')
                for f in files:
                    ReferenceDocument.objects.create(
                        subscription=sub, 
                        file=f,
                        # 如果你的模型里有 filename 字段，可以加上: filename=f.name
                    )

            return JsonResponse({
                'status': 'success', 
                'id': sub.id, 
                'message': f'成功创建订阅并关联了 {len(recipient_objs)} 个接收人'
            })

        except Exception as e:
            print(f"Error creating subscription: {e}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'message': '仅支持 POST 请求'}, status=405)


@require_POST
def delete_report_history(request, pk):
    report = get_object_or_404(ReportHistory, pk=pk)
    subscription_id = report.subscription.id
    report.delete()
    messages.success(request, "简报记录已成功移除。")
    return redirect('ai_subscription:report_history_list', sub_id=subscription_id)

@require_POST
def delete_individual_file(request):
    file_id = request.POST.get('file_id')
    # 获取文件对象
    doc = get_object_or_404(ReferenceDocument, id=file_id)
    
    try:
        # 1. 物理删除文件
        if doc.file and os.path.isfile(doc.file.path):
            os.remove(doc.file.path)
            
        # 2. 数据库记录删除
        doc.delete()
        
        return JsonResponse({'status': 'success', 'message': '文件已移除'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

def trigger_report(request, sub_id):
    subscription = get_object_or_404(Subscription, id=sub_id)
    report = generate_report_with_attachments(subscription)
    
    if report:
        messages.success(request, "简报生成成功！已存入历史记录。")
        return redirect('ai_subscription:report_detail', report_id=report.id)
    else:
        messages.error(request, "AI 生成失败，请检查 API 配置。")
        return redirect('ai_subscription:subs_manage')

def trigger_report_task(request, sub_id):
    # 仅仅是把任务丢进队列，毫秒级响应
    task_generate_ai_report.delay(sub_id)
    
    messages.info(request, "AI 简报生成任务已在后台启动，请稍后在历史记录中查看。")
    # 给出友好提示
    messages.success(request, f"🚀 针对「{subscription.report_title}」的 AI 生成任务已启动！请几分钟后在历史记录中查看。")
    # 返回列表页
    return redirect('ai_subscription:report_history_list', sub_id=sub_id)

@csrf_exempt  # 演示用，实际生产环境建议通过前端配置 CSRF Token
def subscribe_api_print(request):
    if request.method == 'POST':
        try:
            # 1. 提取文本数据 (对应前端 input 的 name 属性)
            user_name = request.POST.get('user_name')
            user_email = request.POST.get('user_email')
            report_title = request.POST.get('report_title')
            keywords = request.POST.get('keywords')
            description = request.POST.get('description')
            period = request.POST.get('period')
            send_time = request.POST.get('send_time')
            format_type = request.POST.get('format')

            # 2. 处理上传的文件 (对应前端 input 的 name="attachments")
            uploaded_files = request.FILES.getlist('attachments')
            
            # 创建存储目录
            upload_path = os.path.join('media', 'ai_docs', user_email)
            if not os.path.exists(upload_path):
                os.makedirs(upload_path)

            saved_files = []
            for f in uploaded_files:
                file_full_path = os.path.join(upload_path, f.name)
                with open(file_full_path, 'wb+') as destination:
                    for chunk in f.chunks():
                        destination.write(chunk)
                saved_files.append(f.name)

            # 3. 打印逻辑（此处可改为数据库 Save 操作）
            print(f"收到订阅：{user_name} ({user_email})")
            print(f"简报标题：{report_title}")
            print(f"已保存文件：{saved_files}")
            print(f"关键词：{keywords}")
            print(f"描述：{description}")
            print(f"周期：{period}")
            print(f"发送时间：{send_time}")
            print(f"格式：{format_type}")

            return JsonResponse({
                'status': 'success',
                'message': 'Django 已成功接收订阅请求',
                'received_data': {
                    'name': user_name,
                    'files_count': len(saved_files)
                }
            })

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'message': '仅支持 POST 请求'}, status=405)