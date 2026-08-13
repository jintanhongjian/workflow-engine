import os
import sys
import base64
import markdown
from email import encoders
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from django.conf import settings

SCOPES = settings.GOOGLE_OAUTH_SCOPES

def check_google_token(token_path='token.json'):
    print(f"--- Google API 授权状态检查 ---")
    
    try:
        # 1. 检查文件是否存在
        if not os.path.exists(token_path):
            print(f"[错误] 未找到 {token_path} 文件！")
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

        # 2. 加载凭据
        creds = Credentials.from_authorized_user_file(token_path)
        
        # 3. 检查凭据有效性
        if creds and creds.valid:
            print(f"[正常] Token 有效。")
            print(f" - 过期时间: {creds.expiry}")
            return True
        
        # 4. 尝试自动刷新
        if creds and creds.expired and creds.refresh_token:
            print(f"[警告] Token 已过期，正在尝试使用 refresh_token 自动续期...")
            creds.refresh(Request())
            
            # 保存刷新后的新 Token
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
            print(f"[成功] Token 续期完成并已更新文件。")
            return True
        else:
            print("原因：可能 refresh_token 已失效，或授权已被撤销。")
            # 删除过期的 token 文件，强制重新授权
            os.remove(token_path)
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

    except Exception as e:
        print(f"[致命异常] 检查过程中出错: {str(e)}")
        return False

def send_email(to_email, title, plain_content, html_content, attachment_paths=[]):
    """
    将 Markdown 报告转换为 HTML 并通过 Google API 发送
    """
    try:
        # 1. 检查/获取凭据
        if not check_google_token('token.json'):
            print(f"[错误] 授权失败，无法操作。")
            return False

        # 2. 加载凭据
        creds = Credentials.from_authorized_user_file('token.json', ['https://www.googleapis.com/auth/gmail.send'])
        service = build('gmail', 'v1', credentials=creds)

        # 2. 给 HTML 套一个简单的样式容器，让邮件更好看
        styled_html = f"""
        <html>
            <body style="font-family: 'PingFang SC', sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
                    <h2 style="color: #4F46E5; border-bottom: 2px solid #F3F4F6; padding-bottom: 10px;">{title}</h2>
                    {html_content}
                    <hr style="border: none; border-top: 1px dashed #ddd;margin: 30px 0;">
                    <p style="font-size: 12px; color: #999; text-align: center;">此邮件由定时提醒系统自动发送</p>
                </div>
            </body>
        </html>
        """
        # 3. 构建邮件对象 (Multipart 支持 HTML 和 纯文本回退)
        message = MIMEMultipart('mixed')
        if isinstance(to_email, (list, tuple, set)):
            to_header = ', '.join([str(item).strip() for item in to_email if str(item).strip()])
        else:
            to_header = str(to_email or '').strip()

        if not to_header:
            raise ValueError('to_email is empty')

        message['to'] = to_header
        message['subject'] = str(title or '')  # 直接用简报标题作为邮件标题

        alt_message = MIMEMultipart('alternative')

        # 纯文本备选（以防邮件客户端不支持 HTML）
        part1 = MIMEText(str(plain_content or ''), 'plain', 'utf-8')
        # HTML 正文
        part2 = MIMEText(str(styled_html or ''), 'html', 'utf-8')

        alt_message.attach(part1)
        alt_message.attach(part2)
        message.attach(alt_message)

        # 挂载附件
        for path in attachment_paths:
            if not path:
                continue
            file_path = str(path)
            if not os.path.exists(file_path):
                continue

            with open(file_path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(file_path)}"')
            message.attach(part)

        # 4. 编码并发送
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId='me', body={'raw': raw_message}).execute()
        
        return True
    except Exception as e:
        print(f"Gmail 发送失败 [{title}]: {e}")
        return False

def send_markdown_report(to_email, report_title, md_content):
    """
    将 Markdown 报告转换为 HTML 并通过 Gmail API 发送
    """
    try:
        # 1. 检查/获取凭据
        if not check_google_token('token.json'):
            print(f"[错误] 授权失败，无法操作。")
            return False

        # 2. 加载凭据
        creds = Credentials.from_authorized_user_file('token.json', ['https://www.googleapis.com/auth/gmail.send'])
        service = build('gmail', 'v1', credentials=creds)

        # 2. 将 Markdown 转换为 HTML
        # 使用 safe 模式并添加常用的扩展（如表格支持）
        html_content = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])
        
        # 给 HTML 套一个简单的样式容器，让邮件更好看
        styled_html = f"""
        <html>
            <body style="font-family: 'PingFang SC', sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
                    <h2 style="color: #4F46E5; border-bottom: 2px solid #F3F4F6; padding-bottom: 10px;">{report_title}</h2>
                    {html_content}
                    <hr style="border: none; border-top: 1px dashed #ddd; margin: 30px 0;">
                    <p style="font-size: 12px; color: #999; text-align: center;">此邮件由 AI 简报系统自动发送</p>
                </div>
            </body>
        </html>
        """

        # 3. 构建邮件对象 (Multipart 支持 HTML 和 纯文本回退)
        message = MIMEMultipart('alternative')
        message['to'] = to_email
        message['subject'] = report_title  # 直接用简报标题作为邮件标题

        # 纯文本备选（以防邮件客户端不支持 HTML）
        part1 = MIMEText(md_content, 'plain')
        # HTML 正文
        part2 = MIMEText(styled_html, 'html')
        
        message.attach(part1)
        message.attach(part2)
        
        # 4. 编码并发送
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId='me', body={'raw': raw_message}).execute()
        
        return True
    except Exception as e:
        print(f"Gmail 发送失败 [{report_title}]: {e}")
        return False

def get_google_sheet_data(spreadsheet_id, range_name, token_path='token.json'):
    """
    获取 Google Sheet 数据
    :param spreadsheet_id: Google Sheet ID (可从URL获取)
    :param range_name: 数据范围 (例如 'Sheet1!A1:D10' 或 'Sheet1')
    :param token_path: token.json 路径
    :return: 包含行列数据的列表
    """
    try:
        # 1. 检查/获取凭据
        if not check_google_token(token_path):
            print(f"[错误] 授权失败，无法获取 Google Sheet 数据。")
            return None
            
        # 2. 加载有效凭据
        creds = Credentials.from_authorized_user_file(token_path, settings.GOOGLE_OAUTH_SCOPES)
        
        # 3. 构建 Sheets API 服务
        service = build('sheets', 'v4', credentials=creds)
        
        # 4. 调用 API 获取数据
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
        values = result.get('values', [])
        
        return values
        
    except Exception as e:
        print(f"获取 Google Sheet 数据失败: {str(e)}")
        return None

