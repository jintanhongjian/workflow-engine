import os.path
import sys
import django
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from django.conf import settings

# 关键：允许在非 HTTPS 环境下运行（本地回调通常是 http://localhost）
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
# 关键：忽略 state 校验错误
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

# 1. 将项目根目录添加到搜索路径（假设脚本在 api_services 文件夹里）
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 2. 设置 Django 环境变量
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'workflow-engine.settings')

# 3. 初始化 Django
django.setup()

# 定义权限范围：仅发送邮件
# 如果以后需要读取或删除邮件，需要修改这里的 SCOPES
SCOPES = settings.GOOGLE_OAUTH_SCOPES

def save_token():
    creds = None
    # 检查是否已有 token.json
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # 如果没有有效凭据，则进行登录
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Token 已过期，正在尝试刷新...")
            creds.refresh(Request())
        else:
            print("正在启动浏览器进行授权...")
            if not os.path.exists('credentials.json'):
                print("错误：当前目录下找不到 credentials.json 文件！")
                return

            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            # 修改这一行，禁止脚本尝试自动打开浏览器
            # 同时指定 host 为 0.0.0.0 (或保持 localhost 但使用 SSH 隧道)
            creds = flow.run_local_server(
                host='localhost',
                port=8080, 
                open_browser=False, # 关键：不自动打开浏览器
                success_message='授权成功！你现在可以关闭此窗口了。'
            )
        
        # 保存凭据供下次使用
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
        print("🎉 授权成功！token.json 已生成。")

if __name__ == '__main__':
    save_token()