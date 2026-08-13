import importlib
"""
URL configuration for workflow-engine project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.views.generic.base import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.urls import re_path
from django.contrib.auth.views import LogoutView
from django.conf.urls.i18n import i18n_patterns

urlpatterns = [
    # 手动切换语言
    path('i18n/', include('django.conf.urls.i18n')),
    path('trans/', include('rosetta.urls')),
    # 当有请求寻找 favicon.ico 时，强制把它重定向到你的新 PNG 图标
    path('favicon.ico', RedirectView.as_view(url=settings.STATIC_URL + 'img/workflow_1.png')),
    ]

urlpatterns += i18n_patterns(
    path('admin/', admin.site.urls),
    # 登录：使用内置 View，指向你的 Tailwind 模板
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    # 登出：Django 5.0 推荐使用 POST 方式
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    # 修改密码页面
    path('password_change/', auth_views.PasswordChangeView.as_view(
        template_name='password_change_form.html',
        success_url='/password_change/done/'
    ), name='password_change'),
    # 修改成功提示页面
    path('password_change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='password_change_done.html'
    ), name='password_change_done'),    
    path('', getattr(importlib.import_module('django.views.generic'), 'TemplateView').as_view(template_name='dashboard.html'), name='home'),
    # 包含订阅应用的路由
    path('subs/', include('ai_subscription.urls')), 
    # 包含审批流应用的路由
    path('workflow/', include('approve_flow.urls', namespace='workflow')), 
    # API 服务页面
    path('api/', include('api_services.urls', namespace='api_services')),
    prefix_default_language=False
)

# 即使 DEBUG=False 也强制提供静态文件
urlpatterns += [
    re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT}),
]
# 在原本的 urlpatterns 后面加上：
# if settings.DEBUG:
#     urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)