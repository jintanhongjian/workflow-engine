from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.db.models import ProtectedError
from django.views.decorators.http import require_POST,require_GET
from django.contrib.auth.decorators import login_required
from django.db import transaction  
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .services import FlowService, ApiResponse, OrgData, CustomJSONEncoder
from .models import (ApproveWorkflow, WorkflowStep, RoleDefinition, 
                     Department,UserRoleAssignment,OrgHier,
                     BusinessObj, TestBusinessApply, 
                     FlowInstance,ApprovalNode,NodeApprover)
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone   
from django.contrib import messages
import json
import logging
logger = logging.getLogger(__name__)


def org_dashboard_view(request):
    return render(request, 'org_management.html')

@require_POST
def api_assign_user_role(request):
    """
    接收前端三位一体分配数据
    payload: { "user_id": 1, "dept_id": 2, "role_ids": [1, 3] }
    """
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        dept_id = data.get('dept_id')
        role_ids = data.get('role_ids') # 数组，因为一个人可以在一个部门身兼数职

        # 清理旧关系 (可选，取决于业务覆盖逻辑)
        # UserRoleAssignment.objects.filter(user_id=user_id, department_id=dept_id).delete()

        # 批量创建新关系
        new_assignments = []
        for rid in role_ids:
            new_assignments.append(UserRoleAssignment(
                user_id=user_id,
                department_id=dept_id,
                role_id=rid,
                assigned_by=request.user # 记录操作人
            ))
        
        UserRoleAssignment.objects.bulk_create(new_assignments)
        
        return ApiResponse.success(message='分配成功')
    except Exception as e:
        return ApiResponse.fail(message=str(e), code=400, status=400)

def api_role_list(request):
    roles = RoleDefinition.objects.filter(is_active=True).values('id', 'name', 'role_code', 'is_active')
    return ApiResponse.success(data=list(roles))

@require_POST
def api_create_role(request):
    try:
        data = json.loads(request.body)
        print("Creating role with data:", data)  # 调试输出，查看前端传来的数据结构
        new_role = RoleDefinition.objects.create(
            name=data.get('name'),
            role_code=data.get('role_code').upper(),
            is_active=data.get('is_active', True)
        )
        return ApiResponse.success(message='角色创建成功')
    except Exception as e:
        return ApiResponse.fail(message=str(e), code=400, status=400)

@require_POST
def api_update_role(request, role_id):
    try:
        role = RoleDefinition.objects.get(id=role_id)
        data = json.loads(request.body)
        # 更新字段
        role.name = data.get('name')
        role.role_code = data.get('role_code').upper()
        role.is_active = data.get('is_active', True)
        role.save()
        
        return ApiResponse.success(message='角色更新成功')
    except RoleDefinition.DoesNotExist:
        return ApiResponse.fail(message='角色不存在', code=404, status=404)
    except Exception as e:
        return ApiResponse.fail(message=str(e), code=500, status=500)

@require_POST
def api_delete_role(request, role_id):
    try:
        role = RoleDefinition.objects.get(id=role_id)
        role.delete()
        return ApiResponse.success(message='角色删除成功')
    except ProtectedError:
        return ApiResponse.fail(message='该角色正在被部门负责人或审批流使用，无法删除', code=400, status=400)
    except Exception as e:
        return ApiResponse.fail(message=str(e), code=500, status=500)

# 顺便检查一下是否还有其他缺少的函数（如 api_user_list）
def api_user_list(request):
    users = OrgHier.objects.all().select_related('user', 'department').values(
        'user__id', 'user__username', 'department__name', 'job_title', 'rank_level'
    )
    return ApiResponse.success(data=list(users))

def api_department_tree(request):
    """返回全量部门树接口"""
    try:
        data = OrgData.get_dept_tree()
        # print("Returning department tree data:", data)  # 调试输出，查看返回的数据结构
        return ApiResponse.success(data=data)
    except Exception as e:
        return ApiResponse.fail(message=str(e), code=500, status=500)

def api_department_members(request, dept_id):
    """
    获取指定部门下的所有成员及角色 (对应前端 showDetail 函数)
    """
    # 这里的查询逻辑需要更丰富，以便在前端弹窗中回显所有信息
    members = OrgHier.objects.filter(department_id=dept_id).select_related('user', 'superior')
    
    data = []
    for m in members:
        # 获取用户在该部门的角色
        assigned_roles = UserRoleAssignment.objects.filter(user=m.user).values_list('role_id', flat=True)
        
        data.append({
            'user_id': m.user.id,
            'username': m.user.username,
            'first_name': m.user.first_name,
            'last_name': m.user.last_name,
            'email': m.user.email,
            'is_active': m.user.is_active,
            'job_title': m.job_title,
            'department_id': m.department_id,
            'superior_id': m.superior_id,
            'superior': m.superior.username if m.superior else "无",
            'roles': list(assigned_roles)
        })
    # print(f"Returning members for department {dept_id}:", data)  # 调试输出，查看返回的成员数据
    return ApiResponse.success(data=data)

@require_POST
def api_create_department(request):
    try:
        data = json.loads(request.body)
        name = data.get('name')
        dept_code = data.get('dept_code')
        parent_id = data.get('parent') or None
        manager_role = data.get('manager_role')

        # 数据校验
        if not name or not dept_code:
            return ApiResponse.fail(message='名称和代码不能为空', code=400, status=400)

        # 创建部门
        new_dept = Department.objects.create(
            name=name,
            dept_code=dept_code,
            parent_id=parent_id,
            manager_role_id=manager_role,
        )

        return ApiResponse.success(data={'id': new_dept.id, 'name': new_dept.name})
    except Exception as e:
        return ApiResponse.fail(message=str(e), code=500, status=500)

@require_POST
def api_update_department(request, dept_id):
    try:
        dept = Department.objects.get(id=dept_id)
        data = json.loads(request.body)
        
        dept.name = data.get('name')
        dept.dept_code = data.get('dept_code')
        # 简单防错：父部门不能是自己
        parent_id = data.get('parent')
        if parent_id and int(parent_id) == dept.id:
            return ApiResponse.fail(message='父部门不能是自己', code=400, status=400)
        dept.parent_id = parent_id or None
        dept.manager_role_id=data.get('manager_role')
        dept.save()

        return ApiResponse.success(data={'id': dept.id, 'name': dept.name})
    except Department.DoesNotExist:
        return ApiResponse.fail(message='部门不存在', code=404, status=404)
    except Exception as e:
        return ApiResponse.fail(message=str(e), code=500, status=500)


@require_POST
@transaction.atomic
def api_create_user(request):
    """
    创建新用户、设置组织关系和角色的统一接口
    """
    try:
        data = json.loads(request.body)
        username = data.get('username')
        first_name = data.get('first_name', '')
        last_name = data.get('last_name', '')
        password = data.get('password')
        job_title = data.get('job_title')
        email = data.get('email')
        department_id = data.get('department')
        superior_id = data.get('superior')
        role_ids = data.get('roles', [])

        # 1. 数据校验
        if not all([username,email, department_id]):
            return ApiResponse.fail(message="用户名、邮箱和部门为必填项", code=400, status=400)
        if User.objects.filter(username=username).exists():
            return ApiResponse.fail(message=f"用户名 '{username}' 已存在", code=400, status=400)

        # 2. 创建 User 对象
        user = User.objects.create_user(username=username, 
                                        password=password,
                                        email=email,
                                        first_name=first_name,
                                        last_name=last_name)

        # 3. 创建 OrgHier 组织层级关系
        OrgHier.objects.create(
            user=user,
            department_id=department_id,
            superior_id=superior_id if superior_id else None,
            job_title=job_title
        )

        # 4. 批量分配角色
        if role_ids:
            assignments = [
                UserRoleAssignment(
                    user=user,
                    department_id=department_id,
                    role_id=role_id,
                    assigned_by=request.user
                ) for role_id in role_ids
            ]
            UserRoleAssignment.objects.bulk_create(assignments)

        return ApiResponse.success(message="用户创建成功")

    except ValidationError as e:
        return ApiResponse.fail(message=", ".join(e.messages), code=400, status=400)
    except Exception as e:
        return ApiResponse.fail(message=str(e), code=500, status=500)


@require_POST
@transaction.atomic
def api_update_user(request, user_id):
    """
    更新用户信息、组织关系和角色的统一接口
    """
    try:
        user = get_object_or_404(User, id=user_id)
        org_hier = get_object_or_404(OrgHier, user=user)
        
        data = json.loads(request.body)
        print("Updating user with data:", data)  # 调试输出，查看前端传来的数据结构
        # 1. 更新 User 模型
        user.username = data.get('username')
        user.first_name = data.get('first_name', '')
        user.last_name = data.get('last_name', '')
        user.email = data.get('email', '')
        user.is_active = data.get('is_active', True)
        
        password = data.get('password')
        if password and password!='':
            user.set_password(password)
        
        user.save()

        # 2. 更新 OrgHier 模型
        org_hier.department_id = data.get('department')
        org_hier.superior_id = data.get('superior') if data.get('superior') else None
        org_hier.job_title = data.get('job_title', '')
        org_hier.save()

        # 3. 更新角色分配 (先删后增)
        department_id = data.get('department')
        UserRoleAssignment.objects.filter(user=user, department_id=department_id).delete()
        
        role_ids = data.get('roles', [])
        if role_ids:
            assignments = [
                UserRoleAssignment(
                    user=user,
                    department_id=department_id,
                    role_id=role_id,
                    assigned_by=request.user
                ) for role_id in role_ids
            ]
            UserRoleAssignment.objects.bulk_create(assignments)

        return ApiResponse.success(message="用户更新成功")

    except ValidationError as e:
        return ApiResponse.fail(message=", ".join(e.messages), code=400, status=400)
    except Exception as e:
        return ApiResponse.fail(message=str(e), code=500, status=500)


'''
workflow_designer_view 设计器主页面视图
'''
# @login_required
def workflow_designer_view(request):
    """
    兼容新建和编辑的可视化设计器视图
    """
    workflow_id = request.GET.get('workflow_id', 'new')  # 默认为 'new', 表示新建模式
    if workflow_id == 'new':
        workflow = None  # 代表新建模式
    else:
        workflow = get_object_or_404(ApproveWorkflow, pk=workflow_id)
    
    return render(request, 'workflow_designer.html', {
        'workflow': workflow,
        'is_new': workflow_id == 'new'
    })

@login_required
def get_workflow_list(request):
    workflows = ApproveWorkflow.objects.all().order_by('-updated_at')
    data = [{
        'id': w.id,
        'name': w.name,
        'code': w.code
    } for w in workflows]
    return ApiResponse.success(data=data)

def check_workflow_code(request):
    code = request.GET.get('code', '').strip().upper()
    if not code:
        return ApiResponse.fail(message="Code is required", code=400, status=400)
    
    # 检查数据库中是否存在该编码
    exists = ApproveWorkflow.objects.filter(code=code).exists()
    
    data = {
        "available": not exists,
        "message": "Code is available" if not exists else "Code already exists"
    }
    return ApiResponse.success(data=data)

def get_workflow_config(request, workflow_id):
    """
    获取指定流程的配置，供前端设计器回显
    """
    try:
        workflow = ApproveWorkflow.objects.get(pk=workflow_id)
        # 预加载关联数据以提高性能
        steps = workflow.steps.all().order_by('order').prefetch_related('roles', 'specific_users')
        
        steps_data = []
        for step in steps:
            # 默认逻辑
            node_type = 'user'
            name = step.name
            order = step.order
            lev= step.level
            # 判断节点类型
            if step.superior_approve:
                node_type = 'superior'
                node_name = '主管审批'
            if step.dept_mgr_approve:
                node_type = 'dept_manager'
                node_name = '部门经理审批'
            if step.roles.exists():
                node_type = 'role'
                node_name = '角色审批'
            if step.specific_users.exists():
                node_type = 'user'
                node_name = '指定人审批'

            steps_data.append({
                "step_id": step.id,
                "level": lev,
                "order": order,
                "name": name,
                "type": node_type,
                "amount_control": step.amount_control,
                "min_amount": float(step.min_amount) if step.min_amount else 0,
                "max_amount": float(step.max_amount) if step.max_amount else "",
                "approve_mode": step.approve_mode,
                # 将 ID 转换为逗号分隔的字符串，方便前端 dataset 存储
                "superior_approve": step.superior_approve,
                "dept_mgr_approve": step.dept_mgr_approve,
                "roles": ",".join([str(r.id) for r in step.roles.all()]),
                "users": ",".join([str(u.id) for u in step.specific_users.all()])
            })
        # print("Returning workflow config:", steps_data)  # 调试输出，查看返回的数据格式 

        return ApiResponse.success(data={
            "flow_code": workflow.code,
            "flow_name": workflow.name,
            "flow_description": workflow.description,
            "remove_duplicate_approvers": workflow.remove_duplicate_approvers,
            "is_active": workflow.is_active,
            "steps": steps_data
        })
    except ApproveWorkflow.DoesNotExist:
        return ApiResponse.fail(message="流程不存在", status=404)

# @require_POST
@transaction.atomic
def save_workflow_design(request, workflow_id):
    # print("Received workflow design data:", request.body)  # 调试输出，查看前端传来的数据格式
    try:
        data = json.loads(request.body)
        print("Parsed workflow design data:", data)  # 调试输出，查看解析后的数据结构
        steps_data = data.get('steps', [])
        
        # 1. 区分流程的新建与获取
        if str(workflow_id) == "0":
            code = data.get('code')
            if ApproveWorkflow.objects.filter(code=code).exists():
                return ApiResponse.fail(
                    message=f"编码 '{code}' 已被其他流程占用，请更换。",
                    status=400
                )        
            workflow = ApproveWorkflow.objects.create(
                code=code,
                name=data.get('name'),
                description=data.get('description', ''),
                remove_duplicate_approvers=data.get('remove_duplicate_approvers', True),
                is_active=data.get('is_active', True),
                creator=request.user or None  # 如果没有登录用户，允许为 None（仅限测试环境）
            )
        else:
            workflow = ApproveWorkflow.objects.get(id=workflow_id)
            # 更新流程基本信息
            workflow.name = data.get('name', workflow.name)
            workflow.description = data.get('description', workflow.description)
            workflow.remove_duplicate_approvers = data.get('remove_duplicate_approvers', workflow.remove_duplicate_approvers)
            workflow.is_active = data.get('is_active', workflow.is_active)
            workflow.save()

        # 2. 收集前端传回的所有 ID 用于排除（删除）
        received_ids = [s.get('step_id') for s in steps_data if s.get('step_id')]
        # print(f"Received step IDs for workflow {workflow.id}: {received_ids}")  # 调试输出，查看前端传来的步骤 ID 列表
        # 3. 删除画布上不再存在的步骤
        workflow.steps.exclude(id__in=received_ids).delete()

        # 4. 增量保存
        for s in steps_data:
            step_id = s.get('step_id')
            
            defaults = {
                'name': s.get('name'),
                'level': s.get('level'),
                'order': s.get('order'),
                'approve_mode': s.get('approve_mode'),
                'superior_approve': s.get('superior_approve'),
                'dept_mgr_approve': s.get('dept_mgr_approve'),
                'amount_control': s.get('amount_control'),
                'min_amount': s.get('min_amount') or 0,
                'max_amount': s.get('max_amount') if s.get('max_amount') else None,
                'permission_tag': s.get('permission_tag', ''),
            }

            # 执行 Upsert
            step, created = WorkflowStep.objects.update_or_create(
                id=step_id, # 如果 step_id 为 None，这里会自动执行插入
                workflow=workflow,
                defaults=defaults
            )

            # 5. 更新多对多关系 (Roles & Users)
            if s.get('roles'):
                step.roles.set(s.get('roles').split(','))
            else:
                step.roles.clear()
                
            if s.get('users'):
                # 假设模型字段名为 specific_users
                step.specific_users.set(s.get('users').split(','))
            else:
                step.specific_users.clear()

        data={
            "status": "success", 
            "workflow_id": workflow.id
        }
        return ApiResponse.success(data=data)
    except ApproveWorkflow.DoesNotExist:
        return ApiResponse.fail(message="流程不存在", status=404)
    except Exception as e:
        logger.error(f"Error saving workflow design: {str(e)}", exc_info=True)
        return ApiResponse.fail(message=str(e), status=500)

def get_workflow_metadata(request):
    """返回供设计器使用的基础数据"""
    roles = RoleDefinition.objects.all().values('id', 'name')
    users = User.objects.filter(
        org_info__is_approver=True
    ).values('id', 'username','org_info__job_title')
    
    # 格式化一下，让前端好用
    formatted_users = [
        {
            "id": u['id'], 
            "username": f"{u['username']} ({u['org_info__job_title'] or '未设职位'})"
        } 
        for u in users
    ]
    
    data = {
        "roles": list(roles),
        "users": formatted_users
    }
    return ApiResponse.success(data=data)

#=====================================================
# 业务测试 API (Business Logic testing APIs) 
#=====================================================

# @login_required
def workflow_test_page(request):
    # 基础配置数据
    workflow_code = request.GET.get('workflow_code')
    departments = Department.objects.all()
    workflows = ApproveWorkflow.objects.filter(is_active=True)
    users = User.objects.all().order_by('username')

    # 获取 TestBusinessApply 对象列表
    # 仅获取那些在流程中且未结案的单据
    active_applies = TestBusinessApply.objects.all().select_related('user', 'department').order_by('-create_date')
    
    # 获取 ContentTypes
    apply_ct = ContentType.objects.get_for_model(TestBusinessApply)
    biz_obj_ct = ContentType.objects.get_for_model(BusinessObj)

    # 找到这些流程对应的 BusinessObj，并获取其对应的原始单据 ID
    active_biz_objs = BusinessObj.objects.filter(
        content_type=apply_ct
    ).values('object_id', 'id')
    # 创建映射字典 {TestBusinessApply_ID: BusinessObj_ID}
    biz_mapping = {item['object_id']: item['id'] for item in active_biz_objs}
    
    # 查找所有未结案的流程实例，并获取它们关联的 BusinessObj 的 ID
    # 这样我们只筛选“正在进行中”的测试
    active_instances = FlowInstance.objects.filter(
        content_type=biz_obj_ct
    ).values('object_id', 'id') # 获取 BusinessObj 的 ID 和自身的 ID

    # 创建一个映射字典 {BusinessObj_ID: Instance_ID} 方便后续匹配
    instance_mapping = {item['object_id']: item['id'] for item in active_instances}


    # 4. 组装前端需要的列表数据
    instances_applies = []
    for apply in active_applies:
        # 通过字典查找，避免在循环中查询数据库
        biz_obj_id = biz_mapping.get(apply.id)
        target_instance_id = instance_mapping.get(biz_obj_id)

        instances_applies.append({
            "id": apply.id,
            "obj_id": biz_obj_id if biz_obj_id else "null",
            "instance_id": target_instance_id if target_instance_id else "null",
        })

    # 5. 准备其他基础数据
    context = {
        'active_applies': active_applies,
        'instances_applied': instances_applies,  # 前端用来标记哪些单据已经有流程在走了
        'workflow_code': workflow_code,
        'workflows': workflows,
        'current_user': request.user,
        'users': users,
        'departments': departments,
    }
    # print("Rendering test page with context:", context)  # 调试输出，查看传递给模板的数据结构
    return render(request, 'test_preview.html', context)

@require_GET
def api_workflow_preview(request):
    """
    URL: /api/workflow/preview/?code=AI_SUB&amount=10000&dept_id=1
    """
    #清除所有数据，必要时执行
    applicant_id = request.GET.get('user_id') or request.user.id # 默认预览人为当前用户
    code = request.GET.get('code')
    dept_id = request.GET.get('dept_id')
    try:
        amount = float(request.GET.get('amount', 0))
    except (ValueError, TypeError):
        return ApiResponse.fail(message="金额参数错误", code=400, status=400)

    if not code:
        return ApiResponse.fail(message="缺失流程编码", code=400, status=400)

    # 获取预测路径
    # 在调用 predict_path 时带上 applicant_id
    path_data = FlowService.predict_path(
        workflow_code=code, 
        amount=amount, 
        department_id=dept_id,
        applicant_id=applicant_id # 关键传参
    )
    
    # for step_data in path_data:
    #     print([role['name'] for role in step_data.get('approvers', []) if role.get('category') != 'Unassigned'])
    
    # 构造可读字符串
    readable_path = " ➔ ".join([step['name'] for step in path_data])
    
    data = {
            "steps": path_data,
            "readable_path": readable_path
        };
    return ApiResponse.success(data=data)

@require_GET
def predict_workflow_path(request):
    """
    一个专门的API端点，用于在不创建任何数据库对象的情况下，
    接收参数并调用 predict_path 函数来预测工作流路径。
    """
    # 1. 从 GET 请求中提取参数
    data = request.GET
    workflow_code = data.get('code')
    user_id = data.get('user_id')
    dept_id = data.get('dept_id')
    amount = data.get('amount', 0)

    if not workflow_code:
        return ApiResponse.fail("必须提供 'code' (流程编码) 参数", code=400)

    # 2. 调用服务层进行路径预测
    predicted_steps = FlowService.predict_path(
        workflow_code=workflow_code,
        department_id=dept_id,
        applicant_id=user_id,
        amount=amount
    )
    
    return render(request, 'approval_preview.html', {
    'steps': json.dumps(predicted_steps, cls=CustomJSONEncoder)
    })
        
def _get_test_response(instance):
    """统一构建实例状态响应"""
    biz_obj = instance.content_object
    # 重新获取最新的路径预测和当前环节审批人
    steps = FlowService.predict_path(
        biz_obj.workflow.code, biz_obj.department_id, biz_obj.applicant_id, biz_obj.amount
    )
    
    if not instance.current_node:
        instance.current_node=ApprovalNode.objects.filter(instance=instance).first()
        instance.save()
    res = instance.current_node.approvers.values_list('id', 'username')
    current_approvers = [{"id": u[0], "name": u[1]} for u in res]
    # print(f"Current approvers for node '{instance.current_node.name}': {current_approvers}")  # 调试输出，查看当前审批人数据

    data= {
        "status": "success",
        "instance_id": instance.id,
        "business_code": biz_obj.business_code,
        "is_finished": instance.is_finished,
        "current_level": instance.current_node.level if instance.current_node else -1,
        "steps": steps,
        "current_approvers": current_approvers
    }
    # print("Instance response data:", data.content)  # 调试输出，查看返回给前端的数据格式
    return ApiResponse.success(data=data)
    
@transaction.atomic
def api_test_submit(request):
    data = json.loads(request.body)
    # print("Received test submission data:", data)  # 调试输出，查看前端传来的数据格式
    try:
        # 获取关联对象
        apply_id = data.get('apply_id') or None
        object_id = data.get('obj_id') or None
        instance_id = data.get('instance_id') or None
        user = User.objects.get(id=data.get('user_id'))
        workflow = ApproveWorkflow.objects.get(code=data.get('flowCode'))
        dept_id = data.get('dept_id')
        department = Department.objects.get(id=dept_id) if dept_id else None
        # 1. 创建 TestBusinessApply 完整记录
        if apply_id=='null' or not apply_id:  # 只有在没有传 apply_id 时才创建新记录，否则视为已存在记录的更新/刷新
            test_apply = TestBusinessApply.objects.create(
                business_code=data.get('business_code', f'TEST{timezone.now().strftime("%Y%m%d%H%M%S")}'),
                business_type=data.get('business_type', '测试业务'),
                application_title=data.get('title', '未命名申请'),
                workflow_code=workflow.code,
                user=user,
                department=department,
                amount=data.get('amount', 0),
                business_description=data.get('business_description', ''),
                create_date=timezone.now()
            )
            # print(f"Submitting test application: user={user.username}, workflow={workflow.name}, department={department.name if department else 'None'}")  # 调试输出，查看提交的数据详情
        else:
            test_apply = TestBusinessApply.objects.get(id=apply_id)
        if object_id=='null' or not object_id:  # 只有在没有传 object_id，否则视为已存在流程的刷新
            # 2. 调用 FlowService 转化为 BusinessObj 并启动流程
            # 传递 workflow.code 字符串以匹配你的核心函数逻辑
            biz_obj = FlowService.send_to_BusinessObj(
                original_obj=test_apply,
                workflow_code=workflow.code
            )
        else:
            ct = ContentType.objects.get_for_model(test_apply)
            biz_obj = BusinessObj.objects.get(content_type=ct, object_id=test_apply.id)
            if instance_id=='null' or not instance_id:
                new_instance = FlowService.start_business_approval_by_obj(biz_obj)
        instance = FlowInstance.objects.get(object_id=biz_obj.id)
        return _get_test_response(instance)
    except Exception as e:
        return ApiResponse.fail(message=str(e), code=400, status=400)
    
def api_test_action(request):
    """模拟审批 API"""
    data = json.loads(request.body)
    # print("Received approval data:", data)  # 调试输出，查看前端传来的数据格式
    instance = FlowInstance.objects.get(id=data['instance_id'])
    operator = User.objects.get(id=data['operator_id'])
    
    if data['action'] == 'PASS':
        FlowService.execute_approve(instance, operator, comment="Lab Test Pass")
    elif data['action'] == 'REJECT':
        FlowService.execute_reject(instance, operator, comment="Lab Test Reject")
    elif data['action'] == 'RETURN':
        FlowService.execute_return(instance, operator, comment="Lab Test Return")
    elif data['action'] == 'CANCEL':
        FlowService.execute_cancel(instance, operator, comment="Lab Test Cancel")
    
    instance.refresh_from_db()
    return _get_test_response(instance)

def api_load_test_instance(request):
    apply_id = request.GET.get('apply_id')
    try:
        # 1. 定位原始单据
        apply = TestBusinessApply.objects.get(id=apply_id)
        
        # 2. 定位中台业务对象
        ct = ContentType.objects.get_for_model(TestBusinessApply)
        biz_obj = BusinessObj.objects.get(content_type=ct, object_id=apply.id)
        biz_obj_id = biz_obj.id if biz_obj else "null"
        
        # 3. 定位当前的流程实例
        # 如果一个单据可能多次发起审批，取最新的那个
        instance = FlowInstance.objects.filter(
            object_id=biz_obj.id
        ).order_by('-id').first()
        instance_id = instance.id if instance else "null"
        
        if not instance:
            return ApiResponse.fail(message="该单据尚未发起审批流程", code=404, status=404)

        # 4. 调用通用的实例状态组装函数 (即之前我们定义的 _get_test_response)
        return _get_test_response(instance)
        
    except Exception as e:
        return ApiResponse.fail(message=f"系统异常: {str(e)}", code=500, status=500)

@require_POST
def delete_workflow(request, workflow_id):
    """
    删除指定的工作流
    """
    try:
        workflow = get_object_or_404(ApproveWorkflow, pk=workflow_id)
        workflow.delete()
        return ApiResponse.success(message=f"工作流 '{workflow.name}' 已成功删除。")
    except ProtectedError:
        return ApiResponse.fail(
            message="无法删除，因为该工作流正在被一个或多个业务对象使用。",
            status=400
        )
    except Exception as e:
        return ApiResponse.fail(message=str(e), status=500)
def workflow_home_view(request):
    """
    导航主页，包含流程设计器、测试中心、组织架构管理等入口
    """
    return render(request, 'workflow_home.html')
