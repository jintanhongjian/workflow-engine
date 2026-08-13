from django.urls import path
from . import views  # 修正导入

app_name = 'api_services'

urlpatterns = [
    path('language/update/', views.update_user_language, name='update_user_language'),
    path('tasks/manage/', views.task_manage_view, name='task_manage'),
    path('tasks/create/', views.custom_task_create_view, name='custom_task_create'),
    path('tasks/<int:task_id>/edit/', views.custom_task_edit_view, name='custom_task_edit'),
    path('logs/<int:log_id>/edit/', views.task_log_edit_view, name='task_log_edit'),
    path('ai/prompts/', views.system_prompt_list, name='system_prompt_list'),
    path('ai/prompts/<int:prompt_id>/delete/', views.system_prompt_delete, name='system_prompt_delete'),
    path('ai/workbench/', views.ai_workbench_view, name='ai_workbench'),
    path('ai/workbench/chat/', views.ai_workbench_chat, name='ai_workbench_chat'),
    path('ai/workbench/skill/details/', views.skill_details, name='skill_details'),
    path('ai/workbench/history/', views.ai_workbench_history, name='ai_workbench_history'),
    path('ai/workbench/conversation/delete/', views.ai_workbench_conversation_delete, name='ai_workbench_conversation_delete'),
    path('ai/workbench/conversation/<uuid:cid>/edit/', views.ai_workbench_conversation_edit, name='ai_workbench_conversation_edit'),
    path('ai/workbench/messages/', views.AIChatMessageListView.as_view(), name='ai_chat_message_list'),
    path('ai/workbench/messages/<int:pk>/update/', views.ai_chat_message_update, name='ai_chat_message_update'),
    path('ai/workbench/messages/<int:pk>/delete/', views.ai_chat_message_delete, name='ai_chat_message_delete'),
]