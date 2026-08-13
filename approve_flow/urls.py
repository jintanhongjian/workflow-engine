from django.urls import path
from . import views  # 修正导入

app_name = 'approve_flow'

urlpatterns = [
    # --- 页面访问路由 ---
    # 组织架构管理主页面 (包含部门树、人员管理等)
    path('org/dashboard/', views.org_dashboard_view, name='org_dashboard'),
    # 1. 部门相关
    path('api/dept-tree/', views.api_department_tree, name='api_dept_tree'),
    path('api/dept/<int:dept_id>/members/', views.api_department_members, name='api_dept_members'),
    # 新增部门接口
    path('api/dept/create/', views.api_create_department, name='api_create_department'),
    path('api/dept/update/<int:dept_id>/', views.api_update_department, name='api_update_department'),    # 2. 角色定义相关
    # 角色相关
    path('api/roles/', views.api_role_list, name='api_role_list'),
    path('api/roles/create/', views.api_create_role, name='api_create_role'),
    path('api/roles/update/<int:role_id>/', views.api_update_role, name='api_update_role'),
    path('api/roles/delete/<int:role_id>/', views.api_delete_role, name='api_delete_role'),

    # 3. 人员组织与分配相关
    path('api/users/', views.api_user_list, name='api_user_list'),
    path('api/user/create/', views.api_create_user, name='api_create_user'),
    path('api/user/update/<int:user_id>/', views.api_update_user, name='api_update_user'),
    path('api/assign-role/', views.api_assign_user_role, name='api_assign_user_role'),
    # ==========================================
    # 1. 页面展示渲染 (Pages)
    # ==========================================
    # 模拟预览中心
    path('test-center/', views.workflow_test_page, name='test_center'),
    # ==========================================
    # 2. 核心设计 API (Designer APIs)
    # ==========================================
     # 流程可视化设计器 (统一使用 str 类型以兼容 'new' 关键字)
    path('design/', views.workflow_designer_view, name='designer'),
    
    # 获取已创建流程列表
    path('api/designer/list/', views.get_workflow_list, name='api_list'),
    
   # 获取设计器所需的元数据 (角色、用户等)
    path('api/designer/metadata/', views.get_workflow_metadata, name='api_metadata'),

    # 获取/加载特定流程配置 (GET)
    path('api/designer/config/<int:workflow_id>/', views.get_workflow_config, name='api_get_config'),

    # 保存流程设计 (POST) - 统一使用 int 区分，新建时传 0
    path('api/designer/save/<int:workflow_id>/', views.save_workflow_design, name='api_save_design'),

    # 删除流程设计 (POST)
    path('api/designer/delete/<int:workflow_id>/', views.delete_workflow, name='api_delete_workflow'),

    # 匹配路径：/workflow/api/designer/check_code/ 
    path('api/designer/check_code/', views.check_workflow_code, name='check_workflow_code'),
    # ==========================================
    # 3. 业务逻辑 API (Business Logic)
    # ==========================================
    # 路径预测预览 API
    path('api/preview/', views.api_workflow_preview, name='api_preview'),
    
    # API: 正式提交测试单据 (POST) - 对应你点击的按钮
    path('api/test-submit/', views.api_test_submit, name='api_test_submit'),
    
    # API: 模拟审批动作 (POST)
    path('api/test-action/', views.api_test_action, name='api_test_action'),
    
    path('api/load-test-instance/', views.api_load_test_instance, name='api_load_test_instance'),

    # 纯路径预测 API (不创建实例)
    path('predict-path/', views.predict_workflow_path, name='predict_workflow_path'),
]