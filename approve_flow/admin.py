from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from decimal import Decimal, InvalidOperation
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import (
    RoleDefinition, UserRoleAssignment, ApproveWorkflow, OrgHier,
    WorkflowStep, Department, FlowInstance, NodeApprover, 
    ApprovalLog, ApprovalNode, 
    BusinessObj, TestBusinessApply,
)
from django import forms
from django.urls import reverse
from django.utils.translation import ngettext
from .services import FlowService


# 颜色配置常量
ACTION_COLORS = {
    'SUBMIT': '#6366f1',  # Indigo
    'APPROVE': '#10b981', # Green
    'REJECT': '#ef4444',  # Red
    'NOTIFY': '#3b82f6',  # Blue
}


class OrgHierInline(admin.StackedInline):
    model = OrgHier
    can_delete = False
    verbose_name = "组织架构信息"
    fk_name = 'user'

class UserAdmin(BaseUserAdmin):
    """在 Django 自带的 User 管理界面中直接修改主管和职位"""
    inlines = (OrgHierInline,)
    list_display = ('username', 'email', 'get_job_title', 'get_superior', 'is_staff')

    def get_job_title(self, obj):
        return obj.org_info.job_title if hasattr(obj, 'org_info') else "-"
    get_job_title.short_description = '职位'

    def get_superior(self, obj):
        return obj.org_info.superior if hasattr(obj, 'org_info') else "-"
    get_superior.short_description = '直接主管'

# 重新注册 User
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# --- 1. 基础架构管理 ---

from django.contrib import admin
from .models import Department, RoleDefinition

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    # 1. 列表页展示字段：名称、代码、父级、主管岗位、当前主管姓名
    list_display = ('indented_name', 'dept_code', 'parent', 'manager_role', 'current_manager_name')
    
    # 2. 搜索框：支持搜部门名和代码
    search_fields = ('name', 'dept_code')
    
    # 3. 过滤器：支持按父级部门过滤
    list_filter = ('parent', 'manager_role')
    
    # 4. 字段布局：将主管相关信息放在一个分组
    fieldsets = (
        ("基础信息", {
            'fields': ('name', 'dept_code', 'parent', 'manager_role')
        }),
    )

    # 自定义列表列：显示缩进名称（体现树形结构）
    def indented_name(self, obj):
        level = 0
        curr = obj.parent
        while curr:
            level += 1
            curr = curr.parent
        return f"{'—' * level} {obj.name}"
    indented_name.short_description = "部门名称"

    # 自定义列表列：显示当前该角色对应的人
    def current_manager_name(self, obj):
        if obj.manager_role:
            # 动态寻找分配了该角色的人，并且限定在当前部门范围内
            assignment = UserRoleAssignment.objects.filter(
                department__id=obj.id,
                role=obj.manager_role
            ).first()
            return f"🚩 {assignment.user.username}" if assignment else "⚠️ 角色未分配人"
        return "-"
    current_manager_name.short_description = "当前负责人"

@admin.register(RoleDefinition)
class RoleDefinitionAdmin(admin.ModelAdmin):
    list_display = ('name', 'role_code', 'is_active')
    search_fields = ('name', 'role_code')

@admin.register(UserRoleAssignment)
class UserRoleAssignmentAdmin(admin.ModelAdmin):
    # 现在可以根据部门和角色进行双重过滤了
    list_display = ('user', 'department', 'role', 'assigned_at')
    list_filter = ('department', 'role', 'assigned_at')
    autocomplete_fields = ['user', 'role', 'department']
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.assigned_by = request.user
        super().save_model(request, obj, form, change)

#--- 2. 流程配置管理 (Template) ---

@admin.register(WorkflowStep)
class WorkflowStepAdmin(admin.ModelAdmin):
    list_display = ('name', 'workflow', 'level', 'order', 'approve_mode', 'superior_approve', 'dept_mgr_approve')
    list_filter = ('workflow', 'approve_mode', 'level')
    search_fields = ('name', 'workflow__name')
    autocomplete_fields = ['workflow', 'roles', 'specific_users']
    
    def get_search_results(self, request, queryset, search_term):
        """
        重写搜索逻辑，实现联动过滤
        """
        # 1. 执行父类默认的搜索
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        
        # 2. 获取来自 FlowInstanceAdmin 转发的 workflow ID
        # Django autocomplete 默认会将表单中的其他字段作为参数传递
        workflow_id = request.GET.get('workflow') 
        
        if workflow_id:
            # 只有当选择了 workflow 时，才过滤该流程下的环节
            queryset = queryset.filter(workflow_id=workflow_id)
            
        return queryset, use_distinct
    
    class Meta:
        verbose_name = "审批环节"
        verbose_name_plural = "审批环节管理"
        ordering = ['workflow', 'name', 'level', 'order']

class WorkflowStepInline(admin.TabularInline):
    model = WorkflowStep
    extra = 1
    # 包含了你新增的 level 和 permission_tag
    fields = ("name",'order', 'level', 'approve_mode','superior_approve', 
              'roles', 'specific_users', 'permission_tag','amount_control','min_amount','max_amount')
    filter_horizontal = ('roles', 'specific_users')

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """
        针对特定字段进行下拉列表筛选
        """
        if db_field.name == "specific_users":
            # 筛选条件：关联的 org_info 中的 is_approver 必须为 True
            kwargs["queryset"] = User.objects.filter(org_info__is_approver=True).distinct()
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    # 强制开启验证
    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        return formset

@admin.register(ApproveWorkflow)
class ApproveWorkflowAdmin(admin.ModelAdmin):
    list_display = ('code','name', 'creator', 'remove_duplicate_approvers','is_active', 'created_at','updated_at')
    inlines = [WorkflowStepInline]
    # 关键：必须定义 search_fields，autocomplete 才能工作
    search_fields = ('code', 'name')    
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.creator = request.user
        super().save_model(request, obj, form, change)
        
    class Meta:
        verbose_name = "审批流程模板"
        verbose_name_plural = "审批流程模板管理"
        ordering = ['code', 'name']

class NodeApproverInline(admin.TabularInline):
    model = NodeApprover
    # 设置 readonly 确保历史轨迹不被随意篡改，只允许查看
    readonly_fields = ('user', 'role_name', 'email', 'status')
    extra = 0
    can_delete = False

@admin.register(ApprovalNode)
class ApprovalNodeAdmin(admin.ModelAdmin):
    # 必须定义 search_fields，autocomplete 功能才能搜索这些字段
    search_fields = ['name', 'instance__workflow__name'] 
    list_display = ['instance', 'name', 'level', 'status', 'is_completed']
    list_filter = ['status', 'is_completed']
    inlines = [NodeApproverInline]

    @admin.display(description="审批人进度")
    def show_summary(self, obj):
        """在列表页显示如：[经理:张三(已处理), 总监:李四(等待中)]"""
        items = obj.approver_details.all()
        html_bits = []
        for item in items:
            color = "#10b981" if item.status == 'COMPLETED' else "#64748b"
            html_bits.append(
                f'<span style="color: {color};">{item.role_name}:{item.user.username}</span>'
            )
        return format_html(", ".join(html_bits))
    
# --- 3. 流程执行监控 (Execution) ---
class ApprovalLogInline(admin.TabularInline):
    model = ApprovalLog
    extra = 0
    # 增加颜色显示的 action_label
    readonly_fields = ('created_at', 'operator', 'action_label', 'step', 'is_returned', 'comment')
    fields = readonly_fields
    can_delete = False

    def action_label(self, obj):
        color = ACTION_COLORS.get(obj.action, '#64748b')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold;">{}</span>',
            color, obj.get_action_display()
        )
    action_label.short_description = "动作"

    def has_add_permission(self, request, obj=None):
        return False
    
class ApprovalNodeInline(admin.TabularInline):
    model = ApprovalNode
    extra = 0
    readonly_fields = ['name', 'level', 'approve_mode', 'status', 'is_completed', 'completed_at']
    # 禁止在 Inline 中随意删除或添加，保证轨迹真实性
    can_delete = False
    max_num = 0

@admin.register(FlowInstance)
class FlowInstanceAdmin(admin.ModelAdmin):
    # 1. 性能优化：使用 select_related 减少 N+1 查询
    list_select_related = ('workflow', 'current_node', 'content_type')
    
    list_display = ('id', 'biz_link', 'progress_bar', 'workflow', 'status_badge','current_node', 'is_finished_label')
    list_filter = ('is_finished', 'workflow', 'status')
    
    # 2. 详情页排版优化
    readonly_fields = ('biz_link', 'content_type', 'object_id')
    fieldsets = (
        ("核心信息", {
            'fields': ('workflow', 'status', 'is_finished')
        }),
        ("关联业务", {
            'fields': ('biz_link', 'content_type', 'object_id'),
        }),
        ("当前状态", {
            'fields': ('current_node',),
        }),
    )
    
    inlines = [ApprovalNodeInline, ApprovalLogInline]
    search_fields = ('id', 'workflow__name', 'current_node__name')
    
    # 3. 联动配置
    autocomplete_fields = ['workflow', 'current_node']
    actions = ['resend_notification', 'mark_as_finished']

    # 如果你想限制只能选择属于当前实例的 Node
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj and 'current_node' in form.base_fields:
            # 过滤下拉框：只显示属于当前 FlowInstance 的节点
            form.base_fields['current_node'].queryset = ApprovalNode.objects.filter(instance=obj)
        return form

    # --- 自定义列显示 ---
    def biz_link(self, obj):
        """跳转到关联的 BusinessObj 详情页"""
        if obj.content_object:
            # 自动识别对应的模型名生成 Admin URL
            model_name = obj.content_type.model
            app_label = obj.content_type.app_label
            url = reverse(f'admin:{app_label}_{model_name}_change', args=[obj.object_id])
            return format_html('<a href="{}" style="font-weight:bold; color:#4f46e5;">🔍 {}</a>', 
                               url, str(obj.content_object))
        return mark_safe('<span style="color: #94a3b8;">未关联</span>')
    biz_link.short_description = "业务单据编号"

    def status_badge(self, obj):
        """状态标签美化"""
        colors = {
            'PENDING': '#f59e0b',  # 橙色
            'PROCESSING': '#3b82f6', # 蓝色
            'FINISH': '#10b981',    # 绿色
            'REJECT': '#ef4444',    # 红色
        }
        color = colors.get(obj.status, '#64748b')
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 10px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = "流程状态"

    def progress_bar(self, obj):
        """真正的动态进度条"""
        if obj.is_finished:
            return mark_safe('<span style="color: #10b981;">● 已完结</span>')
        
        # 计算进度百分比 (假设 ApprovalStep 有 level)
        total_steps = obj.workflow.steps.count() if obj.workflow else 1
        current_level = obj.current_node.level if obj.current_node else 0
        percent = int((current_level / total_steps) * 100) if total_steps > 0 else 0
        
        node_name = obj.current_node.name if obj.current_node else "起始"
        return format_html(
            '''
            <div style="width: 120px; display: inline-block; vertical-align: middle;">
                <div style="width: 100%; background: #f1f5f9; border-radius: 4px; border: 1px solid #e2e8f0;">
                    <div style="width: {}%; height: 6px; background: #6366f1;"></div>
                </div>
                <div style="font-size: 10px; color: #64748b; margin-top: 2px;">{} ({}%)</div>
            </div>
            ''', percent, node_name, percent
        )
    progress_bar.short_description = "流程进度"

    def is_finished_label(self, obj):
        return obj.is_finished
    is_finished_label.boolean = True
    is_finished_label.short_description = "完结"

    # --- 批量动作 ---

    @admin.action(description="📩 重发当前环节通知")
    def resend_notification(self, request, queryset):
        success_count = 0
        for instance in queryset:
            if instance.is_finished or not instance.current_node:
                continue
            
            # 修正逻辑：直接通过 instance_node 获取当前节点已保存的审批人
            # 这样不需要重新计算逻辑，直接利用你新架构里的数据
            approvers = instance.current_node.approvers.all()
            emails = [u.email for u in approvers if u.email]

            if emails:
                FlowService.send_workflow_email(
                    biz_obj=instance.content_object,
                    recipient_list=emails,
                    subject_prefix="【催办】"
                )
                success_count += 1

        self.message_user(request, f"成功为 {success_count} 个流程发送了催办通知。", messages.SUCCESS)

    # --- 资源引入 ---
    class Media:
        js = ('admin/js/workflow_linkage.js',)
        css = {
            'all': ('admin/css/workflow_custom.css',) # 如果有自定义样式的话
        }
        
@admin.register(ApprovalLog)
class ApprovalLogAdmin(admin.ModelAdmin):
    list_display = ('instance', 'operator', 'action', 'step', 'created_at')
    list_filter = ('action', 'created_at')
    readonly_fields = ('instance', 'operator', 'action', 'step', 'comment', 'created_at')
    
    class Meta:
        verbose_name = "审批日志"
        verbose_name_plural = "审批日志监控"
        ordering = ['-created_at']
    
@admin.register(BusinessObj)
class BusinessObjAdmin(admin.ModelAdmin):
    list_display = ('business_code', 'applicant_link', 'formatted_amount', 'status_badge', 'created_at')
    list_filter = ('status', 'department', 'created_at', 'workflow')
    search_fields = ('business_code', 'applicant__username', 'applicant__last_name')
    readonly_fields = ('business_code', 'applicant', 'department', 'amount', 'workflow', 'content_type', 'object_id')
    autocomplete_fields = ['workflow']
    # 增加按钮：直接启动审批 (如果状态是草稿)
    actions = ['trigger_manual_approval']

    def status_badge(self, obj):
        colors = {'DRAFT': '#94a3b8', 'PROGRESS': '#f59e0b', 'APPROVED': '#10b981', 'REJECTED': '#ef4444'}
        return format_html(
            '<span style="color: {}; font-weight: bold;">● {}</span>',
            colors.get(obj.status, '#000'), obj.get_status_display()
        )
    status_badge.short_description = "单据状态"

    @admin.display(description="金额", ordering='amount')
    def formatted_amount(self, obj):
        try:
            # 1. 强制转换为 Decimal，确保它是一个数字类型
            # 即使 obj.amount 是 SafeString 或 None，这里也能处理
            amount_val = Decimal(str(obj.amount))
            
            # 2. 先用 Python 标准格式化生成纯文本字符串
            text_value = "{:,.2f}".format(amount_val)
            
            # 3. 最后再用 format_html 包装 HTML 标签
            return format_html('<span style="font-family: monospace;">¥ {}</span>', text_value)
        except (ValueError, TypeError, InvalidOperation):
            # 如果转换失败，降级显示原始值
            return f"¥ {obj.amount}"

    def applicant_link(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.applicant.id])
        return format_html('<a href="{}">{}</a>', url, obj.applicant.username)
    applicant_link.short_description = "发起人"

    @admin.action(description="手动强制触发审批流程")
    def trigger_manual_approval(self, request, queryset):
        for obj in queryset:
            if obj.status == 'DRAFT':
                obj.trigger_approval()
        self.message_user(request, "选中的单据已尝试进入审批流")
        
    class Meta:
        verbose_name = "业务单据"
        verbose_name_plural = "业务单据管理"
        ordering = ['-created_at']
        


#=====================================================
# 4. 测试业务单据 (Test Business application)
#=====================================================
@admin.register(TestBusinessApply)
class TestBusinessApplyAdmin(admin.ModelAdmin):
    # 1. 列表页展示字段
    list_display = (
        'business_code', 'business_type', 'application_title', 'user', 
        'department', 'amount', 'workflow_code', 'create_date'
    )
    
    # 2. 右侧筛选器
    list_filter = ('business_code', 'business_type', 'workflow_code', 'create_date', 'department')
    
    # 3. 搜索字段
    search_fields = ('business_code', 'application_title', 'business_description', 'workflow_code')
    
    # 4. 优化关联字段选择
    # 注意：workflow_code 已经是 CharField，所以从 autocomplete_fields 中移除
    autocomplete_fields = ['user', 'department']
    
    # 5. 排序
    ordering = ('-create_date',)

    # 6. 自定义动作：一键提交至审批流
    actions = ['make_submit_to_workflow']

    @admin.action(description="🚀 提交选中的单据至审批流")
    def make_submit_to_workflow(self, request, queryset):
        success_count = 0
        error_count = 0
        
        for obj in queryset:
            try:
                # 核心改进：由于 workflow_code 现在是字符串，直接传递即可
                FlowService.send_to_BusinessObj(
                    original_obj=obj,
                    workflow_code=obj.workflow_code,  # 直接使用字符串值
                    user=obj.user,
                    amount=obj.amount
                )
                success_count += 1
            except Exception as e:
                error_count += 1
                self.message_user(request, f"单据 [{obj.application_title}] 送审失败: {str(e)}", messages.ERROR)

        if success_count:
            self.message_user(request, ngettext(
                '成功提交 %d 个单据至审批中台。',
                '成功提交 %d 个单据至审批中台。',
                success_count,
            ) % success_count, messages.SUCCESS)
            
        if error_count:
            self.message_user(request, f"{error_count} 个单据处理异常，请检查流程配置。", messages.WARNING)

    # 7. 核心优化：将文本框 workflow_code 转换为下拉选择框
    def formfield_for_dbfield(self, db_field, **kwargs):
        if db_field.name == "workflow_code":
            # 获取所有激活的流程，构建 (code, name) 元组
            workflow_choices = ApproveWorkflow.objects.filter(is_active=True).values_list('code', 'name')
            choices = [('', '-- 请选择 --')] + [(c[0], f"{c[1]} ({c[0]})") for c in workflow_choices]
            
            # 使用标准的 Django Select 插件，Admin 会自动对其进行样式美化
            kwargs['widget'] = forms.Select(choices=choices)
        return super().formfield_for_dbfield(db_field, **kwargs)

    # 8. 字段布局优化
    fieldsets = (
        ('核心信息', {
            'fields': ('business_code','application_title', 'business_type', 'amount')
        }),
        ('流程配置', {
            'fields': ('workflow_code', 'user', 'department'),
            'description': '请从下拉列表中选择一个有效的流程编码（存储为文本）。'
        }),
        ('补充说明', {
            'classes': ('collapse',), 
            'fields': ('business_description', 'create_date'),
        }),
    )