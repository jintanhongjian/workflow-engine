# workflow-engine/api_services/signals.py
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.utils import translation
from .models import UserProfile # 确保导入了你的模型
from django.conf import settings

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.utils import translation
from .models import UserProfile

@receiver(user_logged_in)
def sync_user_language_on_login(sender, request, user, **kwargs):
    try:
        # 1. 自动获取或创建用户 Profile
        profile, _ = UserProfile.objects.get_or_create(user=user)
        
        # 2. 关键：获取当前请求中的语言意图
        # translation.get_language() 会获取 LocaleMiddleware 识别出的最新语言（来自刚才的 Cookie 切换）
        current_active_lang = translation.get_language()
        session_lang = request.session.get('_language')
        print(f"登录时检测语言: Session语言={session_lang}, 当前活动语言={current_active_lang}, 用户偏好语言={profile.language}")

        # 3. 如果当前页面语言与数据库不同，说明用户刚刚手动切了语言，此时应更新数据库
        if current_active_lang and current_active_lang != profile.language:
            profile.language = current_active_lang
            profile.save(update_fields=['language'])
            print(f"检测到语言变更，已同步数据库偏好为: {current_active_lang}")
        
        # 4. 确保 Session 中记录了最终要用的语言，防止重定向丢失
        target_lang = profile.language
        translation.activate(target_lang)
        request.session['_language'] = target_lang # Django 4+ 使用 '_language' 键
        
    except Exception as e:
        print(f"语言同步失败: {e}")
        
