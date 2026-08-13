# Create your models here.
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey

# ==========================================
# 业务单据调用示例（仅供参考，实际项目中应由具体业务模块定义）
# # 1. 创建业务单据容器
# biz_obj = BusinessObj.objects.create(
#     content_object=my_expense_claim, # 具体的费用报销单
#     business_code="EXP2024001",
#     applicant=request.user,
#     department=request.user.department,
#     amount=1500.00,
#     workflow=selected_workflow,  # 这里指定用户选择的或后台匹配的流程
#     status='DRAFT'
# )

# # 2. 触发审批（这会创建 FlowInstance 并发出第一封邮件）
# biz_obj.trigger_approval()
# ==========================================

class ApproveWorkflow(models.Model):
    # 新增：流程唯一编码，用于 API 调用和逻辑绑定
    code = models.CharField(
        max_length=50, 
        unique=True, 
        db_index=True, 
        verbose_name="流程编码",
        help_text="唯一标识，例如：AI_SUB_001"
    )
    name = models.CharField(max_length=100, verbose_name="流程名称")
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="创建者")
    description = models.TextField(blank=True, verbose_name="流程描述")
    remove_duplicate_approvers = models.BooleanField(default=True, verbose_name="去重审批人")
    is_active = models.BooleanField(default=True, verbose_name="是否激活")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "审批流程"
        verbose_name_plural = "审批流程"
        ordering = ['code', 'name']
        
    def __str__(self):
        # 这样后台下拉框就会显示：财务报销流程 (EXPENSE)
        return f"{self.name} ({self.code})"
        
class Department(models.Model):
    """
    部门表：用于组织架构划分
    """
    name = models.CharField(max_length=100, unique=True, verbose_name="部门名称")
    dept_code = models.CharField(max_length=50, unique=True, verbose_name="部门代码")

    # 指定该部门的“负责人角色” (推荐，支持一人多部或角色变动)
    manager_role = models.ForeignKey(
        'RoleDefinition', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name="负责人角色",
        help_text="关联角色定义表，确定该部门的主管岗位"
    )

    # 增加父级部门字段
    parent = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='children', 
        verbose_name="上级部门"
    )
    
    def get_ancestors(self):
        """
        递归获取所有祖先部门（从近到远）
        """
        ancestors = []
        curr = self.parent
        while curr is not None:
            ancestors.append(curr)
            curr = curr.parent
        return ancestors

    def __str__(self):
        return f"{self.name} ({self.dept_code})"
    
    class Meta:
        verbose_name = "部门"
        verbose_name_plural = "部门管理"
        
class OrgHier(models.Model):
    """
    组织架构层级表 (Organization Hierarchy)
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='org_info'
    )
    department = models.ForeignKey(
        'Department', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name="所属部门"
    )
    
    # 汇报线：指向 User 自身
    superior = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='subordinates',
        verbose_name="直接主管"
    )

    job_title = models.CharField(max_length=100, blank=True, verbose_name="职位名称")
    
    # 是否审批人, 是否可作为指定人员审批
    is_approver = models.BooleanField(default=False, verbose_name="是否审批人")
    # 可选：用于辅助金额权限判断的层级深度
    # 0: CEO, 1: 总监, 2: 经理, 3: 普通员工
    rank_level = models.PositiveIntegerField(default=3, verbose_name="职级权重")

    class Meta:
        verbose_name = "组织架构信息"
        verbose_name_plural = "组织架构管理"
        ordering = ['department__dept_code', 'user__username']

    def __str__(self):
        return f"{self.user.username} ({self.job_title})"

class RoleDefinition(models.Model):
    """
    角色定义表：纯粹的职能定义，不再关联特定部门
    """
    name = models.CharField(max_length=100, verbose_name="角色名称")
    role_code = models.CharField(max_length=50, unique=True, verbose_name="角色代码")
    description = models.TextField(blank=True, verbose_name="职责描述")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "角色定义"
        verbose_name_plural = "角色定义管理"
        ordering = ['role_code', 'name']

    def __str__(self):
        return self.name

class UserRoleAssignment(models.Model):
    """
    用户角色分配表：在这里将 用户、角色、部门 三者绑定
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='role_assignments'
    )
    role = models.ForeignKey(
        RoleDefinition, 
        on_delete=models.CASCADE
    )
    # 关键：将部门关联移到此处，表示该用户在“这个部门”担任“这个角色”
    department = models.ForeignKey(
        Department, 
        on_delete=models.CASCADE,
        null=True, 
        blank=True,
        verbose_name="所属部门"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='assigned_roles'
    )    
    assigned_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "用户角色分配"
        verbose_name_plural = "用户角色分配管理"
        # 约束：同一个用户在同一个部门下不能重复担任同一个角色
        unique_together = (('user', 'role', 'department'),)
        ordering = ['user__username', 'department__dept_code', 'role__role_code']

    def __str__(self):
        dept_str = self.department.name if self.department else "全公司"
        return f"{self.user.username} - {dept_str} - {self.role.name}"

class WorkflowStep(models.Model):
    # 审批模式常量
    MODE_ANY = 'ANY'  # 或签：任一人审批通过即进入下一步
    MODE_ALL = 'ALL'  # 会签：所有人都必须审批通过才进入下一步
    MODE_NOTIFY='NOTIFY' 

    MODE_CHOICES = [
        (MODE_ANY, '任一人审批 (或签)'),
        (MODE_ALL, '全体共同审批 (会签)'),
        (MODE_NOTIFY,'仅通知 (无需审批)'),
    ]

    name = models.CharField(max_length=100, verbose_name="环节名称", default="审批环节")
    workflow = models.ForeignKey('ApproveWorkflow', related_name='steps', on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=0, verbose_name="步骤序号")
    level = models.PositiveIntegerField(default=1, verbose_name="审批层级")
    
    approve_mode = models.CharField(
        max_length=10, 
        choices=MODE_CHOICES, 
        default=MODE_ANY,
        verbose_name="审批模式"
    )

    # --- 寻人逻辑：优先级 superior > roles > specific_users ---
    superior_approve = models.BooleanField(default=False, verbose_name="由直接主管审批")
    dept_mgr_approve = models.BooleanField(default=False, verbose_name="由部门主管审批")
    roles = models.ManyToManyField('RoleDefinition', blank=True, verbose_name="审批角色")
    specific_users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, verbose_name="指定审批人")

    # --- 金额权限 (累进审批核心) ---
    amount_control = models.BooleanField(default=False, verbose_name="启用金额控制")
    min_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    max_amount = models.DecimalField(max_digits=12, decimal_places=2, default=None, null=True, blank=True)

    permission_tag = models.CharField(max_length=100, null=True, blank=True, default='basic_approval', verbose_name="权限标签")
    remarks = models.TextField(blank=True, verbose_name="备注") 

    def clean(self):
        """
        审批步骤业务逻辑校验
        """
        super().clean()

        # 1. 基础逻辑：当前步骤的金额区间校验
        if self.min_amount is not None and self.max_amount is not None:
            if self.max_amount < self.min_amount:
                raise ValidationError({
                    'max_amount': f"最大金额 ({self.max_amount}) 不能小于最小金额 ({self.min_amount})。"
                })

        # 2. 层级递进逻辑：校验与同一流程中其他步骤的关系
        # 注意：这里需要排除掉正在编辑的自己(self.pk)
        if self.workflow_id:
            # 校验同一 Level 下的 min_amount 是否一致（建议同一 Level 金额起点相同）
            # 或者校验递进关系：高 Level 的 min_amount 理论上不应低于低 Level 的 min_amount
            previous_steps = WorkflowStep.objects.filter(
                workflow=self.workflow,
                level__lt=self.level
            ).order_by('-level')

            if previous_steps.exists():
                last_step = previous_steps.first()
                # 校验：当前层级的起点不能低于上一层级的起点
                if self.min_amount is not None and last_step.min_amount is not None:
                    if self.min_amount < last_step.min_amount:
                        raise ValidationError({
                            'min_amount': f"当前层级(L{self.level})的起批金额不能低于上一层级(L{last_step.level})的起批金额({last_step.min_amount})。"
                        })
            # 校验：检查是否存在 Level 冲突但金额区间完全重叠的情况（可选）
            # 逻辑：如果 Level 增加，但 min_amount 却没变，通常意味着这是一个必经的串联环节。

    class Meta:
        ordering = ['level', 'order'] # 优先按层级，再按序号排序
        verbose_name = "审批流程步骤"
        verbose_name_plural = "审批流程步骤"

    def __str__(self):
        return f"{self.name} ({self.level}级) - {self.get_approve_mode_display()}"        
        
class FlowInstance(models.Model):
    """流程实例：只记录‘谁’在‘哪个流程’的‘哪个节点’"""
    workflow = models.ForeignKey(ApproveWorkflow, on_delete=models.PROTECT)
    # 增加 status 冗余字段，方便直接查询当前状态，而不需要每次判断 is_finished
    STATUS_PROCESSING = 'PROCESSING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_CANCELLED = 'CANCELLED'  # 审批申请被取消（失效结束）
    
    STATUS_CHOICES = [
        (STATUS_PROCESSING, '审批中'),
        (STATUS_APPROVED, '已通过'),
        (STATUS_REJECTED, '已驳回'),
        (STATUS_CANCELLED, '已取消'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PROCESSING, db_index=True)

    # 通用的业务对象关联 (Generic Foreign Key)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    current_node = models.ForeignKey(
    'ApprovalNode', # 使用字符串
    on_delete=models.SET_NULL, 
    null=True, 
    related_name='current_for_instances'
    )
    is_finished = models.BooleanField(default=False)
    
    class Meta:
        # 增加复合索引，加快查询某单据的流程实例
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
        ]
        verbose_name = "审批实例"
        verbose_name_plural = "审批实例"  
        ordering = ['-id']      

    def __str__(self):
        obj = self.content_object # 得到 BusinessObj
        if obj and hasattr(obj, 'content_object'):
            actual_apply = obj.content_object # 得到 TestBusinessApply
            business_code = getattr(actual_apply, 'business_code', f"ID-{self.id}")
            return f"{business_code} ({self.workflow.name})"
        return f"ID-{self.id} ({self.workflow.name})"

class ApprovalNode(models.Model):
    """
    审批节点实例：记录每个流程实例在运行时的具体环节状态。
    """
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_PENDING = 'PENDING'
    STATUS_PROCESSING = 'PROCESSING'
    STATUS_SKIPPED = 'SKIPPED'  # 新增：被自动穿    
    
    STATUS_CHOICES = (
        ('PENDING', '待处理'),
        ('PROCESSING', '审批中'),
        ('COMPLETED', '已完成'),
        ('SKIPPED', '已跳过'),
    )

    instance = models.ForeignKey(
        'FlowInstance', 
        on_delete=models.CASCADE, 
        related_name='nodes',
        verbose_name="流程实例"
    )
    step = models.ForeignKey(
        'WorkflowStep', 
        on_delete=models.SET_NULL, 
        null=True,
        verbose_name="原始配置步骤"
    )
    # 冗余 Step 的关键信息，防止模板修改后导致历史轨迹错乱
    name = models.CharField(max_length=100,default='审核步骤', verbose_name="环节名称")
    level = models.IntegerField(default=0, verbose_name="审批层级")
    order = models.IntegerField(default=0, verbose_name="审批顺序")
    approve_mode = models.CharField(
        max_length=10, 
        choices=[('ALL', '会签'), ('ANY', '或签'), ('NOTIFY', '仅通知')], 
        verbose_name="审批模式"
    )
    
    approvers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, 
        blank=True,
        related_name='approval_nodes',
        verbose_name="审批人"
    )

    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='PENDING',
        verbose_name="节点状态"
    )
    is_completed = models.BooleanField(default=False, verbose_name="是否已完成")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="进入环节时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="离开环节时间")

    class Meta:
        verbose_name = "审批实例节点"
        verbose_name_plural = verbose_name
        ordering = ['instance', 'level', 'order']

    def __str__(self):
        return f"{self.name}({self.get_status_display()})"

class NodeApprover(models.Model):
    """
    中间表：记录节点中每个审批人的具体岗位、状态及联系方式
    """
    STATUS_CHOICES = (
        ('PENDING', '等待中'),
        ('NOTIFIED', '已通知'),
        ('COMPLETED', '已处理'),
        ('SKIPPED', '已跳过'),
    )

    # 关联到流程实例
    instance = models.ForeignKey(
        'FlowInstance', 
        default=None,
        on_delete=models.CASCADE, 
        related_name='approver_details',
        verbose_name="流程实例"
    )    
    
    node = models.ForeignKey(
        'ApprovalNode',
        on_delete=models.CASCADE, 
        related_name='approver_details',
        verbose_name="流程步骤"
        )
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    
    # 核心字段
    role_name = models.CharField(max_length=100, verbose_name="岗位角色")
    email = models.EmailField(blank=True, null=True, verbose_name="审批人邮箱")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', verbose_name="个人状态")
    
    order = models.IntegerField(default=0, verbose_name="显示排序")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "节点审批明细"
        verbose_name_plural=verbose_name
        unique_together = ('node', 'user')
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.role_name}: {self.user.username} [{self.get_status_display()}]"

class ApprovalLog(models.Model):
    """
    审批日志表：记录每一笔审批的动作、时间、意见。
    """
    ACTION_APPROVE = 'APPROVE'
    ACTION_REJECT = 'REJECT'
    ACTION_RETURN = 'RETURN'  # 返回到发起人
    ACTION_CANCEL = 'CANCEL'  # 取消审批（撤销到发起人）
    ACTION_SUBMIT = 'SUBMIT'
    ACTION_SKIP='SKIP'
    ACTION_NOTIFY = 'NOTIFY' # 通知
    ACTION_TRANSFER = 'TRANSFER'  # 转办（可选预留）
    ACTION_FINISH = 'FINISH' 

    ACTION_CHOICES = [
        (ACTION_SUBMIT, '提交申请'),
        (ACTION_SKIP, '流程跳转'),
        (ACTION_APPROVE, '审批通过'),
        (ACTION_REJECT, '审批驳回'),
        (ACTION_NOTIFY, '流程通知'),
        (ACTION_TRANSFER, '任务转办'),
        (ACTION_RETURN, '打回重做'),
        (ACTION_CANCEL, '取消审批'),
        (ACTION_FINISH, '审批结束'),
    ]

    # 关联到流程实例
    instance = models.ForeignKey(
        'FlowInstance', 
        on_delete=models.CASCADE, 
        related_name='logs',
        verbose_name="流程实例"
    )
    
    # 记录是在哪个环节审批的
    step = models.ForeignKey(
        'ApprovalNode', 
        on_delete=models.SET_NULL, 
        null=True, 
        verbose_name="审批环节"
    )

    # 指向中间表，这样日志就精确到了“具体的某个人在某个岗位”的操作
    node_approver = models.ForeignKey(
        'NodeApprover', 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='logs',
        verbose_name="审批明细"
    )
        
    # 操作人
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        null=True,
        on_delete=models.CASCADE, 
        verbose_name="操作人"
    )
    
    # 操作动作
    action = models.CharField(
        max_length=20, 
        choices=ACTION_CHOICES, 
        verbose_name="操作动作"
    )
    
    # 可选字段，标记是否为打回重做的日志
    is_returned = models.BooleanField(default=False, verbose_name="是否打回重做") 
    
    # 审批意见
    comment = models.TextField(blank=True, verbose_name="审批意见")
    
    # 操作时间
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="操作时间")

    class Meta:
        verbose_name = "审批日志"
        verbose_name_plural = "审批日志"
        ordering = ['instance','-created_at']

    def __str__(self):
        return f"{self.instance.content_object.applicant} - {self.get_action_display()} - {self.created_at}"
    
class BusinessObj(models.Model):
    """
    业务单据对象：
    作为审批流与具体业务单据之间的“桥梁”和“容器”。
    """
    # 1. 业务类型关联 (Generic Foreign Key)
    # 关联到具体的业务模型，如 Subscription, ExpenseClaim 等
    content_type = models.ForeignKey(
        ContentType, 
        db_index=True,
        on_delete=models.CASCADE,
        verbose_name="业务类型"
    )
    object_id = models.PositiveIntegerField( 
        verbose_name="业务索引ID"
        )
    content_object = GenericForeignKey('content_type', 'object_id')

    # 业务基础信息
    business_code = models.CharField(
        max_length=100, 
        unique=True, 
        verbose_name="单据编号",
        help_text="用于和业务模块的原始单据进行关联索引"
    )

    business_description = models.CharField(
        max_length=500, 
        null=True, 
        blank=True,
        verbose_name="业务描述",
        help_text="用于业务单据的简单描述，方便审批人快速了解单据内容"
    )
    
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.PROTECT, 
        related_name='business_obj_applicants',
        verbose_name="发起人"
    )
    
    department = models.ForeignKey(
        'Department', 
        on_delete=models.PROTECT, 
        verbose_name="申请部门"
    )

    # 审批控制字段
    amount = models.DecimalField(
        max_digits=15, 
        decimal_places=2, 
        default=0.00, 
        verbose_name="业务金额"
    )
    
    # 这里的 permission_tag 可以动态生成，用于引擎匹配 WorkflowStep
    permission_tag = models.CharField(
        max_length=500, 
        blank=True, 
        verbose_name="权限标识"
    )
    
    # 明确关联的流程模板
    workflow = models.ForeignKey(
        'ApproveWorkflow', 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        related_name='instances',
        verbose_name="审批流程"
    )

    # 状态冗余（方便 UI 直接显示单据状态，不用去查 FlowInstance）
    STATUS_CREATED = 'CREATED'
    STATUS_PROGRESS = 'PROGRESS'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_CANCELLED = 'CANCELLED'  # 取消审批（撤销到发起人）
    
    STATUS_CHOICES = [
        (STATUS_CREATED, '创建'),
        (STATUS_PROGRESS, '审批中'),
        (STATUS_APPROVED, '已通过'),
        (STATUS_REJECTED, '已驳回'),
        (STATUS_CANCELLED, '已取消'),
    ]
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default=STATUS_CREATED,
        verbose_name="单据状态"
    )

    # 时间审计
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="审批完成时间")
    rejected_at = models.DateTimeField(null=True, blank=True, verbose_name="驳回时间")
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name="取消时间")
    class Meta:
        verbose_name = "业务审批单"
        verbose_name_plural = "业务审批单管理"
        ordering = ['-created_at']
    
    def trigger_approval(self):
        """
        显式触发审批流的方法
        """
        from .services import FlowService  # 避免循环引用
        
        if self.status != self.STATUS_CREATED:
            return None # 只有创建状态能发起审批

        # 调用我们之前设计的服务层
        instance = FlowService.start_business_approval_by_obj(self)
        
        self.status = self.STATUS_PROGRESS
        self.save(update_fields=['status'])
        return instance

    @property
    def flow_instance(self):
        ct = ContentType.objects.get_for_model(self)
        return FlowInstance.objects.filter(content_type=ct, object_id=self.id).first()

    class Meta:
        verbose_name = "业务审批单"
        verbose_name_plural = "业务审批单管理"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.business_code} - {self.applicant.username} ({self.amount})"
    
class Approval_Attachment(models.Model):
    """
    审批附件表：关联到具体的审批日志，记录审批过程中上传的文件。
    """
    log = models.ForeignKey(
        ApprovalLog, 
        on_delete=models.CASCADE, 
        related_name='attachments',
        verbose_name="审批日志"
    )
    file = models.FileField(upload_to='approval_attachments/', verbose_name="附件文件")
    filename = models.CharField(max_length=255, verbose_name="文件名称")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")

    class Meta:
        verbose_name = "审批附件"
        verbose_name_plural = "审批附件管理"

    def __str__(self):
        return self.filename 
    
#=========================================
# 测试业务单据模型（仅供路径预测和流程测试使用）
#=========================================
class TestBusinessApply(models.Model):
    """
    通用业务申请模型（测试用）
    用于对接 FlowService.send_to_BusinessObj
    """
    # 基础信息
    business_code = models.CharField(
        max_length=100, 
        default='TEST2024001',
        unique=True, 
        verbose_name="单据编号",
        help_text="用于和业务模块的原始单据进行关联索引"
    )
    business_type = models.CharField(max_length=50, verbose_name="业务类型")
    application_title = models.CharField(max_length=200, verbose_name="申请标题")
    
    # 审批核心字段 (FlowService 会优先反射这些字段)
    workflow_code = models.CharField(
        max_length=50, 
        default='TEST_FLOW',
        verbose_name="流程编码",
        help_text="请输入已定义的流程 Code，如：EXPENSE_FLOW"
    )
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="申请人")
    department = models.ForeignKey('Department', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="申请部门")
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="申请金额")
    
    # 描述与日期
    business_description = models.TextField(null=True, blank=True, verbose_name="业务描述")
    create_date = models.DateTimeField(default=timezone.now, verbose_name="创建日期")

    class Meta:
        verbose_name = "测试业务申请"
        verbose_name_plural = verbose_name
        ordering = ['-create_date']

    def __str__(self):
        return f"[{self.business_type}] {self.application_title}"