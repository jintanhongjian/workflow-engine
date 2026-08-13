from django.db import transaction, models
from django.utils import timezone
from decimal import Decimal
from django.conf import settings
from django.http import JsonResponse
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
from .models import (
    RoleDefinition, UserRoleAssignment, ApproveWorkflow, OrgHier,
    WorkflowStep, Department, FlowInstance, NodeApprover, 
    ApprovalLog, ApprovalNode, 
    BusinessObj, TestBusinessApply,
)
from api_services.email_service import MailService 
from api_services.models import EmailConfig, UserProfile
from django.contrib.auth import get_user_model
import json
import logging

logger = logging.getLogger(__name__)


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)

class ApiResponse:
    """
    统一响应格式：
    {
        "code": 200,          # 业务状态码
        "success": true,      # 快速判断标识
        "message": "描述信息", # 提示文字
        "data": { ... }       # 实际数据载体
    }
    """
    @staticmethod
    def success(code=200, message="Success", data=None):
        return JsonResponse({
            'code': code,
            'status': "Success",
            'success': True,
            'message': message,
            'data': data or {}
        }, status=200)

    @staticmethod
    def fail( code=400, message="Error", data=None, status=400):
        return JsonResponse({
            'code': code,
            'status': "Error",
            'success': False,
            'message': message,
            'data': data or {}
        }, status=status)

    @staticmethod
    def unauthorized(message="未授权或登录失效"):
        return ApiResponse.fail(message=message, code=401, status=401)

class FlowService:
    # ==========================================
    # 1. 核心路由与寻人 (Core Engine - Private)
    # ==========================================

    @classmethod
    @transaction.atomic
    def start_business_approval_by_obj(cls, biz_obj):
        """
        基于现有的 BusinessObj 启动流程
        """
        if not biz_obj:
            print("businessObj not exist.")
            return ApiResponse.fail(message="businessObj not exist.", code=400, status=400)
        workflow = biz_obj.workflow
        if not workflow.is_active:
            return ApiResponse.fail(message=f'所选流程未激活', code=400, status=400)
        
        # 2. 创建审批实例
        instance = FlowInstance.objects.create(
            workflow=workflow,
            content_type=ContentType.objects.get_for_model(biz_obj),
            object_id=biz_obj.id,
            current_node=None, # 初始不指定当前节点，后续根据第一步类型决定是否直接流转
            is_finished=False,
        )

        # 2. 预测路径并生成节点快照
        # 建议 predict_path 内部已经处理好了金额过滤
        steps_data = cls.predict_path(
            workflow.code, 
            biz_obj.department_id, 
            biz_obj.applicant_id, 
            biz_obj.amount
        )

        if not steps_data:
            # 特殊情况：如果预测路径为空（例如金额极小且无硬性环节），直接结案
            instance_finish(instance)
            return ApiResponse.success(message="流程已自动结案，无需审批", data={"instance_id": instance.id})
        
        # 批量获取 WorkflowStep 对象，避免在循环中重复查询数据库 (优化 N+1)
        step_ids = [s['stepid'] for s in steps_data]
        step_objs = {step.id: step for step in WorkflowStep.objects.filter(id__in=step_ids)}

        first_node = None
        for i, step_data in enumerate(steps_data):
            node = ApprovalNode.objects.create(
                instance=instance,
                step=step_objs.get(step_data['stepid']),
                name=step_data['name'],
                level=step_data['level'],
                order=step_data.get('order', 0),
                approve_mode=step_data['approve_mode'],
                status='PENDING'
            )
            if i == 0:
                first_node = node            
            # 写入预解析的审批人
            approver_ids = step_data.get('approver_ids')
            if approver_ids:
                # 关联 ManyToMany 字段 (如果 ApprovalNode 还有这个字段)
                node.approvers.set(approver_ids)        
                approve_mode=node.approve_mode
                if approve_mode != "NOTIFY":        
                    # 批量获取 User 对象，避免在循环中重复查询（N+1 问题优化）
                    user_map = {u.id: u for u in get_user_model().objects.filter(id__in=approver_ids)}
                    # 预处理角色列表
                    roles_list = [role['name'] for role in step_data.get('approvers', []) 
                                if role.get('category') != 'Unassigned']
                    # 创建节点审批明细
                    for i, uid in enumerate(approver_ids):
                        # 从预查的字典中获取 User 对象
                        user_obj = user_map.get(uid)
                        current_role = roles_list[i] if i < len(roles_list) else "No role"
                        # 显式创建中间表记录
                        NodeApprover.objects.create(
                            instance=instance,
                            node=node,
                            user=user_obj,           # 这里必须是 User 实例对象
                            role_name=current_role,
                            email=user_obj.email,    # 对象属性访问
                            status='PENDING',
                            order=i                  # 建议使用 i 作为组内排序
                        )

        # 3. 开启第一个节点
        cls.step_start(instance,first_node)
        
        # 3. 记录提交日志
        ApprovalLog.objects.create(
            instance=instance, 
            step=None, 
            node_approver=None,
            operator=biz_obj.applicant,
            action=ApprovalLog.ACTION_SUBMIT, 
            comment="提交审批申请"  if settings.DEBUG else "提交审批申请-Test" 
        )
        return instance

    @staticmethod
    def _find_next_node(instance, current_level):
        """
        统一寻路逻辑：实际流转与路径预测共用此逻辑。
        """
        potential_steps = ApprovalNode.objects.filter(
            instance=instance,
            level__gt=current_level
        ).order_by('level')

        for step in potential_steps:
            return step
        return None

    @staticmethod
    def get_users_by_ids(user_ids):
        users=get_user_model().objects.filter(id__in=user_ids)
        return users

    # ==========================================
    # 2. 业务接口 (API)
    # ==========================================

    @classmethod
    @transaction.atomic
    def send_to_BusinessObj(cls, original_obj, workflow_code=None, business_code=None, user=None, department=None,
                            business_description=None, amount=None, tag="", overwrite=False):
        """
        从业务单据实例创建 BusinessObj。
        支持从 original_obj 自动提取：申请人、部门、金额。
        """
        # 自动识别单据类型
        content_type = ContentType.objects.get_for_model(original_obj)
        model_name = content_type.model.upper()
        biz_obj = BusinessObj.objects.filter(
            content_type=content_type, 
            object_id=original_obj.id).first()
        print(f'original object id:{original_obj.id}')
        if biz_obj:
            print(f'bussiness object id:{biz_obj.id}')
            if overwrite:
                instance = FlowInstance.objects.filter(object_id=biz_obj.id).first()
                if instance:
                    print(f'instance id:{instance.id}')
                    instance.delete()            
                biz_obj.delete()
            else:
                return ApiResponse.fail(message=f'业务对象已经存在，ID:{biz_obj.id}.', code=400, status=400)    
        # 2. 智能提取必要字段 (优先使用传入参数，否则尝试从对象反射)
        # 申请人：尝试获取 applicant, user, 或 creator 字段
        applicant = getattr(original_obj, 'applicant', 
                                   getattr(original_obj, 'user', 
                                          getattr(original_obj, 'creator', user)))
        
        # 部门：尝试获取 department 或从申请人档案中获取
        dept = getattr(original_obj, 'department', department)
        if not dept and hasattr(applicant, 'org_info'): # 假设 User 关联了 org_info
            dept = applicant.org_info.department

        # 金额：尝试获取 amount, total_price, 或 money
        final_amount = getattr(original_obj, 'amount', 
                                        getattr(original_obj, 'total_amount', amount))

        # 3. 校验流程是否存在
        # 如果未传 workflow_code，可以尝试从 original_obj 的某个字段读取，或者报错
        code =  getattr(original_obj, 'workflow_code', workflow_code)
        try:
            workflow = ApproveWorkflow.objects.get(code=code, is_active=True)
        except ApproveWorkflow.DoesNotExist:
            return ApiResponse.fail(message=f"无法启动审批：流程编码 [{code}] 无效或未激活", code=400, status=400)

        # 4. 生成规范的业务编号
        # 格式：类型简写-日期-主键ID (例如：EXPENSE-20260209-15)
        timestamp = timezone.now().strftime('%Y%m%d')
        business_code = getattr(original_obj, 'business_code', business_code) or f"{model_name}-{timestamp}-{original_obj.id}"

        # 5. 创建 BusinessObj 实例
        biz_obj = BusinessObj.objects.create(
            content_type=content_type,
            object_id=original_obj.id,
            business_code=business_code,
            business_description=business_description or str(original_obj)[:200], # 简要描述，限制长度
            applicant=applicant,
            department=dept,
            amount=final_amount,
            workflow=workflow,  # 这里将 BusinessObj 与流程模板关联
            permission_tag=tag if settings.DEBUG else "Test" # 仅在调试环境保留标签，生产环境清空以免泄露
        )

        # 6. 自动触发 FlowInstance 启动逻辑 (如果需要)
        instance = cls.start_business_approval_by_obj(biz_obj)

        logger.info(f"业务单据 [{business_code}] 已成功转化为审批中台对象")
        return biz_obj

    @classmethod
    def no_next_step_action(cls, instance, action_type="APPROVE"):
        """
        辅助函数：判断当前实例是否没有下一步了（即当前节点是最后一个节点或没有节点）
        """
        if action_type == "APPROVE":
            if instance.status == instance.STATUS_PROCESSING:
                cls.instance_finish(instance)
                return instance.STATUS_APPROVED  # 已经结束或没有当前节点，无需处理
            elif instance.status in [instance.STATUS_APPROVED, instance.STATUS_REJECTED]:
                return ApiResponse.fail(message=f'流程已结束，当前状态为： {instance.status}', code=400, status=400)
            elif instance.status == instance.STATUS_CANCELLED:
                return ApiResponse.fail(message=f'流程已撤销，无法审批，当前状态为： {instance.status}', code=400, status=400)
            else:
                return ApiResponse.fail(message=f'当前没有有效的审批环节，无法审批，当前状态为： {instance.status}', code=400, status=400)

    @classmethod
    def step_start(cls, instance, step):
        """
        辅助函数：将指定实例的指定环节标记为待审批
        """
        instance.current_node = step
        instance.status = instance.STATUS_PROCESSING
        instance.save()        
        instance.content_object.status = BusinessObj.STATUS_PROGRESS
        instance.content_object.save()
        step.status = ApprovalNode.STATUS_PENDING
        step.save()

        cls._trigger_step_notification(instance, action_type="TODO")
        return True;

    @classmethod
    def step_processing(cls, instance, step, operator=None,comment=None):
        """
        辅助函数：将指定实例的指定环节标记为审批中
        """
        instance.content_object.status = BusinessObj.STATUS_PROGRESS
        instance.content_object.save()
        step.status = ApprovalNode.STATUS_PROCESSING
        step.save()
        instance.status = instance.STATUS_PROCESSING
        instance.save()
        current_approver=NodeApprover.objects.filter(
            node=step,
            user=operator
        ).first()
        current_approver.status="COMPLETED"
        current_approver.save()
        # 记录审批日志
        ApprovalLog.objects.create(
            instance=instance, 
            step=step, 
            node_approver=current_approver,
            operator=operator,
            action=ApprovalLog.ACTION_APPROVE, 
            comment=comment if settings.DEBUG else f"{comment}-Test"
        )
        return True;

    @classmethod
    @transaction.atomic  # 建议加上事务，确保状态更新和日志创建要么全成功，要么全失败
    def step_complete(cls, instance, step, operator=None,comment=None):
        """
        辅助函数：标记环节完成并清理剩余审批人
        """
        # 1. 更新业务对象和实例状态
        biz_obj = instance.content_object
        biz_obj.status = BusinessObj.STATUS_PROGRESS
        biz_obj.save()
        
        instance.status = FlowInstance.STATUS_PROCESSING
        instance.save()
        
        # 2. 更新当前环节节点状态
        step.status = ApprovalNode.STATUS_COMPLETED
        step.is_completed = True
        step.save()
        
        # 处理剩余审批人 (修复点：先获取对象，再批量更新)
        pending_approvers = NodeApprover.objects.filter(
            node=step,
            status='PENDING'
        )
        # 执行批量更新
        pending_approvers.update(status='SKIPPED')
        # 跳过记录日志
        current_approver=NodeApprover.objects.filter(
            node=step,
            user=operator
        ).first()
        ApprovalLog.objects.create(
            instance=instance,
            step=step,
            node_approver=current_approver, 
            action=ApprovalLog.ACTION_SKIP,
            comment=f"因环节已达成匹配条件，系统自动跳过其他审批人"
        )                
        return True
    
    @classmethod
    def instance_finish(cls, instance):
        """
        辅助函数：判断指定实例是否已完成
        """
        instance.content_object.status = BusinessObj.STATUS_APPROVED
        instance.content_object.save()
        current_step=instance.current_node
        current_step.status = ApprovalNode.STATUS_COMPLETED
        current_step.is_completed = True
        current_step.save()
        instance.status=instance.STATUS_APPROVED
        instance.is_finished=True
        instance.save()
        ApprovalLog.objects.create(
            instance=instance,
            step=current_step,
            node_approver=None, 
            action=ApprovalLog.ACTION_FINISH,
            comment=f"审批流程结束"
        )        
        cls._trigger_step_notification(instance, action_type="FINISH")
        return True;

    @classmethod
    def instance_reject(cls, instance, operator=None,comment=None):
        """
        辅助函数：将指定实例标记为驳回
        """
        instance.content_object.status = BusinessObj.STATUS_REJECTED
        instance.content_object.save()
        current_step=instance.current_node
        current_step.status = ApprovalNode.STATUS_COMPLETED
        current_step.is_completed = True
        current_step.save()
        instance.status=instance.STATUS_REJECTED
        instance.is_finished=True
        instance.save()
        current_approver=NodeApprover.objects.filter(
            node=current_step,
            user=operator
        ).first()
        current_approver.status="COMPLETED"
        current_approver.save()
        # 处理剩余审批人 (修复点：先获取对象，再批量更新)
        pending_approvers = NodeApprover.objects.filter(
            instance=instance,
            status='PENDING'
        )
        # 执行批量更新
        pending_approvers.update(status='SKIPPED')  
        # 记录审批日志              
        ApprovalLog.objects.create(
            instance=instance, 
            step=current_step,
            node_approver=current_approver, 
            operator=operator,
            action=ApprovalLog.ACTION_REJECT, 
            comment=comment if settings.DEBUG else f"{comment}-Test"
        )
        cls._trigger_step_notification(instance, action_type='REJECT')
        return True;

    @classmethod
    def instance_return(cls, instance, operator=None,comment=None):
        biz_obj = instance.content_object
        # 1. 将流程重置到初始状态
        first_step = cls._find_next_node(instance, 0)
        current_step=instance.current_node               
        current_approver=NodeApprover.objects.filter(
            node=current_step,
        ).first()
        instance_nodes = ApprovalNode.objects.filter(instance=instance)
        for step in instance_nodes:
            step.status = ApprovalNode.STATUS_PENDING
            step.is_completed = False
            step.save()
        instance.current_node = first_step
        instance.status = instance.STATUS_PROCESSING
        instance.is_finished = False
        instance.save()
        instance_approvers = NodeApprover.objects.filter(
            instance=instance,
        )
        instance_approvers.update(status='PENDING')
        ApprovalLog.objects.create(
            instance=instance, 
            step=current_step, 
            node_approver=current_approver,
            operator=operator,
            action=ApprovalLog.ACTION_RETURN, 
            comment=comment if settings.DEBUG else f"{comment}-Test"
        )
        ApprovalLog.objects.filter(instance=instance,
                                   is_returned=False,
                                   action=ApprovalLog.ACTION_APPROVE
                                   ).update(is_returned=True) # 标记所有日志为打回重做，便于后续分析
        cls._trigger_step_notification(instance, action_type='RETURN')
        return True;

    @classmethod
    def instance_cancel(cls, instance, operator=None,comment=None):
        """
        辅助函数：将指定实例标记为撤销
        """
        instance.content_object.status = BusinessObj.STATUS_CANCELLED
        instance.content_object.save()
        current_step=instance.current_node
        if current_step:
            current_step.status = ApprovalNode.STATUS_COMPLETED
            current_step.is_completed = True
            current_step.save()
        instance.status=instance.STATUS_CANCELLED
        instance.is_finished=True
        instance.save()
        current_approver=NodeApprover.objects.filter(
            node=current_step,
            user=operator
        ).first()
        current_approver.status="COMPLETED"
        current_approver.save()
        
        # 处理剩余审批人 (修复点：先获取对象，再批量更新)
        pending_approvers = NodeApprover.objects.filter(
            instance=instance,
            status='PENDING'
        )
        # 执行批量更新
        pending_approvers.update(status='SKIPPED') 
        ApprovalLog.objects.create(
            instance=instance, 
            step=current_step,
            node_approver=current_approver,
            operator=operator,
            action=ApprovalLog.ACTION_CANCEL, 
            comment=comment if settings.DEBUG else f"{comment}-Test"
        )
        cls._trigger_step_notification(instance, action_type='CANCEL')
        return True;
    
    @classmethod
    def instance_transfer(cls, instance, new_approver, operator=None,comment=None):
        """
        辅助函数：将指定实例转办给新的审批人
        """
        current_step = instance.current_node
        current_step.approvers.add(new_approver)
        current_step.save()
        approver_count=NodeApprover.objects.filter(
            node=current_step,
        ).count()
        user_obj = get_user_model().objects.filter(id=new_operator).first()
        transfer_role = f'{user_obj.username}[被授权]'
        NodeApprover.objects.create(
            instance=instance,
            node=current_step,
            user=user_obj,           
            role_name=transfer_role,
            email=user_obj.email,    
            status='PENDING',
            order=approver_count + 1                
        )
        current_approver=NodeApprover.objects.filter(
            node=current_step,
            user=operator
        ).first()
        current_approver.status="SKIPPED"
        current_approver.save()
        # 记录转办日志
        ApprovalLog.objects.create(
            instance=instance, 
            step=current_step,
            node_approver=current_approver,
            operator=operator,
            action=ApprovalLog.ACTION_TRANSFER, 
            comment=(comment + f" -> 转办给 {new_approver.username}" if settings.DEBUG else f"{comment}-Test") 
        )
        cls._trigger_step_notification(instance, action_type="TRANSFER", operator=new_approver)
        return True

    @classmethod
    @transaction.atomic
    def execute_approve(cls, instance, operator, comment=""):
        step = instance.current_node
        if not step:
            response = cls.no_next_step_action(instance, action_type="APPROVE")
            return response
        if instance.status != instance.STATUS_PROCESSING:
            return ApiResponse.fail(message=f'流程当前状态为： {instance.status}，无法审批', code=400, status=400)

        cls.step_processing(instance, step, operator, comment)

        completed = cls._is_step_complete(instance, step)
        print(f"审批动作执行：instance_id={instance.id}, step_id={step.id}, completed={completed}")  # 调试输出，查看审批后环节完成状态
        finished = cls._is_finished(instance)
        print(f"审批动作执行：instance_id={instance.id}, finished={finished}")  # 调试输出，查看审批后流程完成状态

        # 判定当前环节是否完成 (会签/或签判定)
        if completed:
            print("当前环节已完成，正在流转到下一环节...")  # 调试输出，查看当前环节完成后是否触发流转
            # 确保当前环节状态正确（已完成）
            cls.step_complete(instance, step, operator, comment)
            # 进入关键逻辑：寻找下一个“实质性”环节
            cls._move_to_next_valid_step(instance, step)
        # 更新实例状态为待审批（如果是会签或或签，先标记为待审批，等判定完成后再更新当前节点）
        elif finished:
            print("流程满足结案条件，正在结案...")  # 调试输出，查看流程结案触发情况
            cls.instance_finish(instance)
        return ApiResponse.success(data=instance.status)

    @classmethod
    @transaction.atomic
    def execute_reject(cls, instance, operator, comment=""):
        """补充：驳回逻辑"""
        if instance.status != instance.STATUS_PROCESSING:
            return ApiResponse.fail(message=f'流程当前状态为： {instance.status}，无法驳回', code=400, status=400)
        cls.instance_reject(instance, operator,comment)
        return ApiResponse.success(data=instance.status)

    @classmethod
    @transaction.atomic
    def execute_return(cls, instance, operator, comment=""):
        """补充：打回重做逻辑"""
        if instance.status != instance.STATUS_PROCESSING:
            return ApiResponse.fail(message=f'流程当前状态为： {instance.status}，无法打回', code=400, status=400)
        cls.instance_return(instance, operator, comment)
        return ApiResponse.success(data=instance.status)
    
    @classmethod
    @transaction.atomic
    def execute_cancel(cls, instance, operator, comment=""):
        if instance.status not in [instance.STATUS_PROCESSING]:
            return ApiResponse.fail(message=f'流程当前状态为： {instance.status}，无法撤销', code=400, status=400)
        cls.instance_cancel(instance, operator, comment)
        return ApiResponse.success(data=instance.status)

    @classmethod
    def execute_transfer(cls, instance, operator, new_approver, comment=""):
        if instance.status != instance.STATUS_PROCESSING:
            return ApiResponse.fail(message=f'流程当前状态为： {instance.status}，无法转办', code=400, status=400)
        if not new_approver:
            return ApiResponse.fail(message=f'转办必须指定新的审批人', code=400, status=400)
        cls.instance_transfer(instance, new_approver, operator, comment)
        return ApiResponse.success(data=instance.status)

    @classmethod
    def _is_step_complete(cls, instance, step):
        """
        判断当前环节是否已完成
        :param instance: 流程实例
        :param step: 当前审批环节对象
        :param total_approvers: 该环节定义的总审批人数
        """
        # 获取该实例在当前环节的所有“通过”记录
        pass_count = NodeApprover.objects.filter(
            node=step,
            status='COMPLETED', 
        ).count()
        
        approvers = step.approvers.all()
        total_approvers = len(approvers)
        print(f'已审批人数为：{pass_count}，流程审批人数为：{total_approvers}.')

        if step.approve_mode == 'ALL':  # 会签：所有人必须通过
            return pass_count >= total_approvers
        elif step.approve_mode == 'ANY':   # 或签：一人通过即可
            return pass_count >= 1
        elif step.approve_mode == 'NOTIFY': # 仅通知：不需要审批，直接算完成
            return True

        return False  # 默认逻辑

    @classmethod
    def _is_finished(cls, instance):
        """
        判断实例是否已满足结案条件
        """
        step = instance.current_node
        if not step:
            return True  # 没有当前节点，视为已结案
        
        
        if cls._is_step_complete(instance, step):
            return True  # 当前环节的权限已满足金额控制要求，可以结案
                
        next_step = cls._find_next_node(instance, step.level)
        if not next_step:
            return True

        return False  # 默认逻辑

    @classmethod
    def _move_to_next_valid_step(cls, instance, current_step, max_iterations=10):
        """
        核心优化：自动穿透 NOTIFY 环节，直到找到需要人工审批的环节或结束
        """
        next_step = cls._find_next_node(instance, current_step.level)
        operator = instance.content_object.applicant
        print(f'operator:{operator}')
        comment="[系统] 仅通知环节，已自动流转"
        # 寻找下一个物理层级的步骤
        if not next_step:
            cls.instance_finish(instance)
            return None
        # --- 重点：处理 NOTIFY 模式 ---
        if next_step.approve_mode == 'NOTIFY':
            # 1. 记录系统自动执行日志
            ApprovalLog.objects.create(
                instance=instance, 
                step=next_step,
                node_approver=None, 
                action=ApprovalLog.ACTION_NOTIFY, 
                comment=comment if settings.DEBUG else "{comment}-Test"
            )
            # 先标记为待审批，虽然实际上不需要审批，但保持状态一致性
            cls.step_start(instance, next_step)  
            # 更新实例状态并继续流转
            cls.step_complete(instance, next_step, operator, comment)
            # 递归：继续寻找下一个有效步骤
            max_iterations -= 1
            if max_iterations <= 0:
                return ApiResponse.fail(message=f'Exceeded maximum iterations in _move_to_next_valid_step', code=500, status=500)
            else:
                return cls._move_to_next_valid_step(instance, next_step, max_iterations)
        else:
            cls.step_start(instance, next_step)
            return next_step

    @classmethod
    def _trigger_step_notification(cls, instance, action_type="TODO", new_approver=None):
        """
        私有方法：根据步骤寻人并触发邮件
        :param action_type: TODO(待办), NOTIFY(知会), FINISH(结果反馈)
        """
        step=instance.current_node
        biz_obj = instance.content_object
        if not step:
            ids = [biz_obj.applicant_id] if biz_obj.applicant_id else []
        else:
            ids = instance.current_node.approvers.values_list('id') if instance.current_node else []
        res = FlowService.get_users_by_ids(ids)
        emails = [u.email for u in res if u.email]
        print(f"Triggering notification for action_type={action_type}, approvers={emails}")  # 调试输出，查看通知触达的用户邮箱列表
        prefix_map = {
            "TODO": "【待审批】",
            "NOTIFY": "【知会】",
            "APPROVED": "【审批通过】",
            "REJECT": "【审批驳回】",
            "CANCEL": "【审批撤销】",
            "RETURN": "【审批退回】",
            "TRANSFER": "【审批转办】",
            "FINISH": "【审批完成】"
        }

        # 如果是结案或驳回，通知人改为申请人
        if action_type in ["FINISH", "REJECT","RETURN","CANCEL"]:
            emails = [biz_obj.applicant.email] if biz_obj.applicant.email else []
        if action_type == "TRANSFER":
            if not new_approver:
                return ApiResponse.fail(message=f'Not found new approver.', code=400, status=400)
            res = FlowService.get_users_by_ids([new_approver])
            emails = [u.email for u in res if u.email]
            
        print(f'{prefix_map.get(action_type, "【流程通知】")},{instance.current_node.name}发送邮件给: {emails}.')

        if emails:
            cls.send_workflow_email(
                biz_obj=biz_obj,
                recipient_list=emails,
                subject_prefix=prefix_map.get(action_type, "【流程通知】")
            )

    @classmethod
    def get_obj_traces(cls, business_code):
        # 获取 ContentTypes
        biz_obj_ct = ContentType.objects.get_for_model(BusinessObj)

        # 找到这些流程对应的 BusinessObj
        active_biz = BusinessObj.objects.filter(
            business_code=business_code
        ).first()

        # 查找所有未结案的流程实例
        active_instance = FlowInstance.objects.filter(
            content_type=biz_obj_ct,
            object_id=active_biz.id
        ).first() # 获取 BusinessObj 的 ID 和自身的 ID

        return active_biz, active_instance
    
    @classmethod
    def send_workflow_email(cls, biz_obj, recipient_list, subject_prefix="【审批通知】", attachments=None):
        """
        业务级发送函数：将 BusinessObj 转化为异步邮件任务
        """
        # 1. 获取当前活跃的邮件配置（用于获取发件人地址）
        config = EmailConfig.objects.filter(is_active=True).first()
        if not config:
            logger.error("邮件发送失败：未找到启用的邮件服务器配置")
            return False

        from_email = f"{config.from_name} <{config.smtp_user}>"
        
        # 2. 构建邮件标题
        subject = f"{subject_prefix} {biz_obj.workflow.name} - {biz_obj.business_code}"

        # 3. 提取 BusinessObj 数据到 Context（序列化为字典以便 Celery 传输）
        context = {
            'workflow_name': biz_obj.workflow.name,
            'business_code': biz_obj.business_code,
            'applicant': biz_obj.applicant.username,
            'department': biz_obj.department.name if biz_obj.department else "无",
            'description': biz_obj.business_description or "无",
            'amount': f"{biz_obj.amount:,.2f}",
            'submit_date': biz_obj.created_at.strftime('%Y-%m-%d %H:%M'),
            'detail_url': f"https://your-oa.com/approve/{biz_obj.id}/", # 根据实际路由配置
        }

        # 4. 指定模板
        template = 'approval_notification.html'

        # 5. 调用 Celery 异步任务
        # 注意：attachments 如果包含字节流，需确保其可被序列化（建议传递文件路径）
        if not settings.DEBUG:
            send_async_email.delay(
                subject=subject,
                from_email=from_email,
                recipients=recipient_list,
                template=template,
                context=context,
                attachments=attachments
            )
        
        logger.info(f"已提交异步邮件任务: {biz_obj.business_code}")
        return True

    @classmethod
    def get_document_approval_status(cls, business_code):
        """
        获取业务单据的整体审批状态及详细进度
        :param business_code: 业务单据编码
        :return: dict 包含状态、进度百分比、当前环节等
        """
        # 1. 获取业务关联对象
        biz_obj = BusinessObj.objects.filter(
            business_code=business_code
        ).first()
        # 2. 找到对应的流程实例
        # 假设 FlowInstance 通过 content_type 和 object_id 关联业务单据
        biz_ct = ContentType.objects.get_for_model(biz_obj)
        instance = FlowInstance.objects.filter(
            content_type=biz_ct, 
            object_id=biz_obj.id
        ).first()

        if not instance:
            data = {
                "instance_id": None,
                "status": "NO_INSTANCE",
                "status_display": "未找到审批流程",
                "progress": 0,
                "current_node": None,
                "is_finished": False,
                "last_update": None
            }
            return ApiResponse.fail(message=f'未找到对应的审批流程实例', data=data, code=404, status=404)
                

        # 3. 计算进度：获取所有节点及完成情况
        all_nodes = ApprovalNode.objects.filter(instance=instance)
        all_approvers = NodeApprover.objects.filter(instance=instance)
        all_logs = ApprovalLog.objects.filter(instance=instance).order_by('-created_at')
        total_nodes = all_nodes.count()
        completed_nodes = all_nodes.filter(is_completed=True).count()
        # 计算百分比
        progress_percent = int((completed_nodes / total_nodes) * 100) if total_nodes > 0 else 0

        # 获取节点状态
        nodes_info = []
        for node in all_nodes:
            approvers = all_approvers.filter(node=node)
            approver_info = []
            for approver in approvers:
                approver_info.append({
                    "user_id": approver.user.id,
                    "username": approver.user.username,
                    "role_name": approver.role_name,
                    "status": approver.status,
                    "updated_at": approver.updated_at.strftime('%Y-%m-%d %H:%M:%S')
                })
            log_info = []
            for log in all_logs.filter(step=node):
                if log.node_approver and log.node_approver.user:
                    log_info.append({
                        "operator_id": log.operator.id if log.operator else None,
                        "username": log.operator.username if log.operator else "系统",
                        "role_name": log.node_approver.role_name if log.node_approver else "系统",
                        "action": log.action,
                        "comment": log.comment,
                        "timestamp": log.created_at.strftime('%Y-%m-%d %H:%M:%S')
                    })
            nodes_info.append({
                "is_current": instance.current_node.id == node.id if instance.current_node else False,
                "name": node.name,
                "level": node.level,
                "status": node.status,
                "is_completed": node.is_completed,
                "approvers": approver_info,
                "logs": log_info
            })

        # 获取当前待办节点的人员
        current_approvers = []
        if instance.current_node:
            current_approvers = list(NodeApprover.objects.filter(
                node=instance.current_node,
                status='PENDING'
            ).values('user__username', 'role_name'))

        data = {
            "business_code": biz_obj.business_code,
            "object_id": biz_obj.object_id,
            "instance_id": instance.id,
            "status": instance.status,
            "status_display": instance.get_status_display(),
            "progress": progress_percent,
            "nodes": nodes_info,
            "is_finished": instance.is_finished,
            "last_update": instance.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        }
        return ApiResponse.success(data=data)

    @classmethod
    def get_dept_manager(cls, department):
        """
        获取指定部门的负责人
        """
        # 从角色分配表中查找
        if department.manager_role:
            assignment = UserRoleAssignment.objects.filter(
                department=department,
                role=department.manager_role,
                user__is_active=True
            ).first()
            if assignment:
                return assignment.user
                
        return None
        
    # ==========================================
    # 3. Predict and test utilities (路径预测与测试工具)
    # ==========================================    
    
    @classmethod
    def predict_path(cls, workflow_code, department_id=None, applicant_id=None, amount=0):
        # print(f'''Predicting path for workflow_code={workflow_code}, 
        #       department_id={department_id}, 
        #       applicant_id={applicant_id}, 
        #       amount={amount}''')
        """
        预测路径：逻辑与 execute_approve 完全同步
        """
        workflow = ApproveWorkflow.objects.filter(code=workflow_code, is_active=True).first()
        if not workflow: return []
        path = []
        curr_level = 0
        trace_user_id = applicant_id
        trace_dept_id = department_id
        visited_steps = set()
        remove_duplicates = workflow.remove_duplicate_approvers # 是否去除上一步的重复审批人，默认开启

        for _ in range(20): # 安全计数
            step = cls.flow_find_next_step(workflow, curr_level)
            if not step or step.id in visited_steps:
                break
            
            visited_steps.add(step.id)
            res = cls.flow_fetch_approvers(step, trace_dept_id, trace_user_id)
            # print(res)
            # 主管溯源更新
            if step.superior_approve and res['manager_id']:
                trace_user_id = res['manager_id']
            # 部门负责人溯源更新（注意：部门负责人审批通常是基于部门而非个人，因此这里更新 trace_dept_id 以便下一步继续寻人）
            if step.dept_mgr_approve and res['parent_dept_id']:
                trace_dept_id = res['parent_dept_id']
            
            # 修改 mode 的显示逻辑
            mode_display = "或签"
            if step.approve_mode == 'ALL': mode_display = "会签"
            elif step.approve_mode == 'NOTIFY': mode_display = "仅通知 (自动跳转)"
            
            step_info = {
                "stepid": step.id,
                "level": step.level,
                "order": step.order,
                "name": step.name,
                "approver_ids": [u.id for u in res['users']],
                "approvers": res['names'],
                "approve_mode": step.approve_mode,
                "mode_display": mode_display,
                "is_notify": step.approve_mode == 'NOTIFY', # 前端可据此变色
                "is_superior": step.superior_approve,
                "amount_control": step.amount_control,
                "min_amount": step.min_amount,
                "max_amount": step.max_amount,
                "permission_tag": step.permission_tag,
            }
            # 去除上一步的重复审批人（如果有）
            # print(f"Predicted step: {step_info}")
            if path and remove_duplicates:
               for appr in step_info['approver_ids']:
                   if appr in path[-1]['approver_ids']:
                    #    print(f"Removing duplicate approver {appr},{[d for d in step_info['approvers'] if d.get('user_id') == appr]} from step {step_info['level']}")
                       step_info['approver_ids'].remove(appr)
                       # 从 approvers 列表中移除具有匹配 user_id 的字典
                       step_info['approvers'] = [d for d in step_info['approvers'] if d.get('user_id') != appr]
            # 结案判定
            if step.amount_control:
                is_amount_covered = ((step.min_amount is None or step.min_amount <= Decimal(amount)) 
                and (step.max_amount is None or Decimal(amount) <= step.max_amount))
                if not is_amount_covered:
                    break
            curr_level = step.level

            
            path.append(step_info)        

        return path

    @classmethod
    def flow_find_next_step(cls, workflow, current_level):
        """
        统一寻路逻辑：实际流转与路径预测共用此逻辑。
        """
        potential_steps = workflow.steps.filter(
            level__gt=current_level
        ).order_by('level', 'order')

        for step in potential_steps:
            return step
        return None

    @classmethod
    def flow_fetch_approvers(cls, flowstep, dept_id, source_user_id):
        """
        统一寻人逻辑：按照优先级去重并保留身份标识。
        优先级：直接主管 > 职能角色 > 指定人
        """
        final_users = {} # {user_id: user_obj} 保证 User 对象唯一
        final_names = {} # {user_id: display_name} 保证同一人只保留最高优先级的名称标签
        found_manager_id = None
        parent_dept_id = None
        roles_categories = {
            'Superior': "主管",
            'Manager': "部门负责人",
            'Title_Role': "职能角色",
            'Spec_User': "指定人",
            'Delegated': "被授权",
            'Unassigned':"未指定",
        }

        # --- 1. 获取直接主管 (最高优先级) ---
        if getattr(flowstep, 'superior_approve', False):
            trace_user = get_user_model().objects.filter(id=source_user_id).first()
            if trace_user:
                hier = OrgHier.objects.select_related('superior').filter(user=trace_user).first()
                if hier and hier.superior:
                    u = hier.superior
                    final_users[u.id] = u
                    final_names[u.id] = {'user_id': u.id, 'category':'Superior','name':f"{u.username}[{roles_categories['Superior']}]"} # 标记最高优先级的头衔
                    found_manager_id = u.id
                else:
                    # 占位符，提示配置缺失
                    final_names[f"missing_{trace_user.id}"] = {'user_id': f"missing_{trace_user.id}", 'category':'Unassigned','name':f"UnAssigned[{trace_user.username}][{roles_categories['Superior']}]"} # 标记最高优先级的头衔
                    # final_names[f"missing_{trace_user.id}"] = f"未配置[{trace_user.username}]的{roles_categories['Superior']}"

        if getattr(flowstep, 'dept_mgr_approve', False):
            trace_user = cls.find_approver_in_dept(dept_id)
            parent_dept = Department.objects.filter(id=dept_id).first().parent
            if parent_dept:
                parent_dept_id = parent_dept.id
            else:
                parent_dept_id = None
            if trace_user:
                u = trace_user
                if u.id not in final_users:
                    final_users[u.id] = u
                    final_names[u.id] = {'user_id': u.id, 'category':'Manager','name':f"{u.username}[{roles_categories['Manager']}]"} # 如果该用户已是主管，则不会覆盖上面的名称
            else:
                # 占位符，提示配置缺失
                final_names[f"missing_dept_{dept_id}"] = {'user_id': f"missing_dept_{dept_id}", 'category':'Unassigned','name':f"UnAssigned[DeptID:{dept_id}][{roles_categories['Manager']}]"} # 标记最高优先级的头衔
                # final_names[f"missing_dept_{dept_id}"] = f"未配置部门ID[{dept_id}]的{roles_categories['Manager']}"

        # --- 2. 获取职能角色 (中等优先级) ---
        if flowstep.roles.exists():
            assignments = UserRoleAssignment.objects.filter(role__in=flowstep.roles.all()).filter(
                Q(department_id=dept_id) | Q(department__isnull=True)
            ).select_related('user')
            
            for a in assignments:
                u = a.user
                if u.id not in final_users:
                    final_users[u.id] = u
                    final_names[u.id] = {'user_id': u.id, 'category':'Title_Role','name':f"{u.username}[{roles_categories['Title_Role']}]"} # 如果该用户已是主管，则不会覆盖上面的名称

        # --- 3. 获取指定用户 (最低优先级) ---
        if flowstep.specific_users.exists():
            for u in flowstep.specific_users.all():
                if u.id not in final_users:
                    final_users[u.id] = u
                    final_names[u.id] = {'user_id': u.id, 'category':'Spec_User','name':f"{u.username}[{roles_categories['Spec_User']}]"}

        # 整理结果，保持 ID 对应的名称一致
        approvers={
            "users": list(final_users.values()),
            "names": list(final_names.values()),
            "manager_id": found_manager_id,
            "parent_dept_id": parent_dept_id
        }
        return approvers

    @classmethod
    def find_approver_in_dept(cls, dept_id, hier_level=0):
        """
        在部门树中向上递归寻找指定角色的用户
        """
        # 查找部门role_code对应的用户
        dept = Department.objects.filter(id=dept_id).first()
        mgr_role = dept.manager_role
        if not mgr_role:
            return None
        # print(dept.name, mgr_role.name)
        dept_mgr = UserRoleAssignment.objects.filter(
            department_id=dept_id,
            role=mgr_role,
            user__is_active=True
        ).first()

        while hier_level <= 0:
            if hier_level == 0 and dept_mgr:
                return dept_mgr.user
            else:
                parent_dept = dept.parent
                if not parent_dept:
                    return None
                print(parent_dept.name, parent_dept.manager_role.name if parent_dept.manager_role else "无角色")
                parent_dept_id = parent_dept.id
                return cls.find_approver_in_dept(parent_dept_id, hier_level - 1)    
                        
        # 3. 最终没找到
        return None
    
class OrgData:
    @classmethod
    def get_dept_tree(cls):
        """
        一次性获取所有部门并构建递归树结构
        """
        # 1. 获取所有部门数据
        # 使用 values 可以显著减少内存开销，并方便转换为字典
        depts = Department.objects.all().values('id', 'name', 'dept_code', 'parent_id', 'manager_role_id','manager_role__name')
        
        # 2. 建立 ID 映射表，方便快速查找父节点
        dept_map = {}
        for dept in depts:
            dept_map[dept['id']] = {
                'id': dept['id'],
                'name': dept['name'],
                'code': dept['dept_code'],
                'manager_role': dept['manager_role_id'] or '未设置',
                'manager': UserRoleAssignment.objects.filter(
                    department_id=dept['id'],
                    role__name=dept['manager_role__name']
                    ).first().user.username if UserRoleAssignment.objects.filter(department_id=dept['id'], role__name=dept['manager_role__name']).exists() else '未设置',
                'parent_id':dept['parent_id'],
                'children': []  # 预留子节点列表
            }
        
        # 3. 构建树形结构
        tree = []
        for dept in depts:
            node = dept_map[dept['id']]
            parent_id = dept['parent_id']
            
            if parent_id is None:
                # 没有父节点，说明是根节点
                tree.append(node)
            else:
                # 找到父节点，并将当前节点挂载到父节点的 children 中
                parent_node = dept_map.get(parent_id)
                if parent_node:
                    parent_node['children'].append(node)          
        return tree

    @classmethod
    def get_user_profile(cls,request, user_id=None):
        # 如果没传 ID 则查本人
        target_id = user_id or request.user.id
        User = get_user_model()
        
        try:
            user_obj = User.objects.select_related('org_info__department').prefetch_related(
                'role_assignments__role', 
                'role_assignments__department'
            ).get(id=target_id)
            
            org_info = getattr(user_obj, 'org_info', None)
            
            data = {
                "user": {
                    "username": user_obj.username,
                    "email": user_obj.email,
                    "job_title": org_info.job_title if org_info else "-",
                    "rank_level": org_info.rank_level if org_info else 3,
                    "superior": org_info.superior.username if org_info and org_info.superior else "无"
                },
                "primary_dept": {
                    "name": org_info.department.name if org_info and org_info.department else "未分配",
                    "code": org_info.department.dept_code if org_info and org_info.department else ""
                },
                # 提取职责角色：用户在哪些部门担任哪些角色
                "functional_roles": [
                    {
                        "role_name": assignment.role.name,
                        "dept_name": assignment.department.name if assignment.department else "公司全员",
                        "assigned_at": assignment.assigned_at.strftime("%Y-%m-%d")
                    } for assignment in user_obj.role_assignments.all()
                ]
            }
            return ApiResponse.success(data)
            
        except User.DoesNotExist:
            return ApiResponse.fail("用户不存在", code=404)
