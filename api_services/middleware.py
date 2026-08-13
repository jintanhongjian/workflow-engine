from django.shortcuts import redirect
from django.urls import reverse
from django.conf import settings
from django.utils import translation
from .models import UserProfile

class SaveLanguagePreferenceMiddleware:
    """
    如果用户已登录，且当前页面语言与数据库不一致，则异步/顺便更新数据库
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # 只针对已登录用户处理
        if request.user.is_authenticated:
            current_lang = translation.get_language()
            # 注意：为了性能，建议在数据库查询上做一点缓存处理，
            # 或者只在特定路径（如 set_language 之后）触发
            user_profile = getattr(request.user, 'profile', None) # 假设 related_name='profile'
            if user_profile and user_profile.language != current_lang:
                user_profile.language = current_lang
                user_profile.save(update_fields=['language'])
                
        return response
    
class LoginRequiredMiddleware:
    """
    全站登录校验中间件：
    除了白名单页面，所有请求必须经过身份验证。
    """
    def __init__(self, get_response):
        self.get_response = get_response
        # 定义不需要登录即可访问的路径
        self.white_list = [
            reverse('login'),      # 登录页面
            '/admin/',             # Django 管理后台（它自带校验）
            '/static/',            # 静态资源
            '/api/public/',        # 假设你以后有的公开接口
        ]

    def __call__(self, request):
        # 1. 检查用户是否已登录
        if not request.user.is_authenticated:
            # 2. 如果未登录，且访问的路径不在白名单中，跳转到登录页
            if not any(request.path.startswith(url) for url in self.white_list):
                return redirect(settings.LOGIN_URL)
        path = request.path
        # 必须允许 set_language 路径通过，否则 Cookie 无法写入
        if request.path == '/i18n/setlang/':
            return self.get_response(request)
        response = self.get_response(request)
        return response

from django.utils import translation
class UserLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # 优先从数据库 Profile 获取
            user_lang = getattr(request.user.userprofile, 'language', None)
            if user_lang:
                translation.activate(user_lang)
        
        response = self.get_response(request)
        return response