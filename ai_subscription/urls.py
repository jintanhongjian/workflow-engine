from django.contrib import admin
from django.urls import path, include
from ai_subscription import views
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns

app_name = 'ai_subscription'  # 设置命名空间

urlpatterns = [
    # 订阅管理页面
    path('subs_manage/', views.SubscriptionListView.as_view(), name='subs_manage'),
    # 新订阅页面
    path('subs_ai/', views.subs_ai, name='subs_ai'),
    #提交保存订阅内容
    path('api/subscribe/', views.subscribe_api, name='subscribe_api'),
    # 编辑订阅页面：/subscription/42/edit/
    path('subscription/<int:pk>/edit/', views.SubscriptionUpdateView.as_view(), name='subscription_update'),
    # 删除订阅页面：/subscription/42/delete/
    path('subscription/<int:pk>/delete/', views.SubscriptionDeleteView.as_view(), name='subscription_delete'),
    # 手动生成订阅报告
    path('subscription/trigger/<int:sub_id>/', views.trigger_report, name='trigger_report'),
    # 删除单个文件的 API 接口：/api/delete-file/
    path('api/delete-file/', views.delete_individual_file, name='api_delete_file'),
    # 查看某个订阅的所有历史：/history/42/
    path('history/<int:sub_id>/', views.report_history_list, name='report_history_list'),
    # 删除简报
    path('history/<int:pk>/delete/', views.delete_report_history, name='delete_report_history'),
    # 查看单篇内容：/report/105/
    path('report/<int:report_id>/', views.report_detail, name='report_detail'),
    ]

# 在原本的 urlpatterns 后面加上：
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)