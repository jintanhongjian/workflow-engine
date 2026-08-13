import os
import uuid
import base64
from api_services.skills.decorators import skill, register_skill

# 推迟导入 RPALite，避免在无显示界面的 Linux (Headless) 环境下由于依赖 (如 PyAutoGUI) 抛出异常
def get_rpalite_instance():
    try:
        from RPALite import RPALite
        return RPALite()
    except Exception as e:
        print(f"Warning: Failed to import/init RPALite: {e}")
        return None

@register_skill
def get_desktop_screenshot_rpalite(save_path: str = "") -> str:
    """
    使用 RPALite 获取桌面截图
    """
    try:
        # 实例化 RPALite
        rpa = get_rpalite_instance()
        if rpa is None: raise RuntimeError("RPALite disabled")
        
        # 决定保存路径
        if not save_path:
            save_path = os.path.join(os.getcwd(), f"screenshot_{uuid.uuid4().hex[:8]}.png")
            
        # RPALite 通常的截图方法可能是 capture_screenshot, screenshot 等
        # 我们这里假设为 screenshot 方法，请根据具体 API 版本调整
        if hasattr(rpa, 'screenshot'):
            rpa.screenshot(save_path)
        elif hasattr(rpa, 'capture_screenshot'):
            rpa.capture_screenshot(save_path)
        else:
            # 如果不确定，可以尝试一些 fallback 的 pyautogui / rpa.core 实现
            import pyautogui
            screenshot = pyautogui.screenshot()
            screenshot.save(save_path)
            
        return f"截图成功，已保存至: {save_path}"
        
    except Exception as e:
        return f"截图失败: {str(e)}"

@register_skill
def open_windows_program(program_path, *args):
    """
    使用 RPALite 打开指定的 Windows 应用程序。
    :param program_path: 要打开的程序路径或命令 (例如 'notepad.exe', 'calc', 'C:\\Program Files\\...\\app.exe')
    :param args: 传递给程序的额外启动参数
    :return: 启动成功返回 True，否则返回 False
    """
    try:
        rpa = get_rpalite_instance()
        if rpa is None: raise RuntimeError("RPALite disabled")
        print(f"尝试使用 RPALite 启动程序: {program_path} {args}")
        
        # 常见 RPALite 或底层 RPA 工具的启动/运行 API 名称
        if hasattr(rpa, 'run_application'):
            rpa.run_application(program_path, *args)
        elif hasattr(rpa, 'open_application'):
            rpa.open_application(program_path, *args)
        elif hasattr(rpa, 'start_process'):
            rpa.start_process(program_path, *args)
        else:
            raise NotImplementedError("未找到 RPALite 中的显式程序启动方法。")
            
        print(f"成功调用 RPALite 启动了程序。")
        return True
        
    except Exception as e:
        print(f"RPALite 启动程序异常: {str(e)}。准备尝试后备系统方法...")
        
        try:
            import subprocess
            cmd = [program_path] + list(args)
            # 使用 Popen 后台运行，避免阻塞当前进程
            subprocess.Popen(cmd)
            print(f"使用 subprocess.Popen 成功启动了程序。")
            return True
        except Exception as e2:
            print(f"后备 subprocess 启动也失败: {str(e2)}")
            # 针对 Windows 的原生支持兜底
            if hasattr(os, 'startfile'):
                try:
                    os.startfile(program_path)
                    print(f"兜底: 使用 os.startfile 成功启动了程序。")
                    return True
                except Exception as e3:
                    print(f"os.startfile 同样失败: {str(e3)}")
            return False

@register_skill
def open_url_with_browser(url: str) -> str:
    """
    使用 RPALite (或后备系统方法) 在默认浏览器中打开指定的网页。
    :param url: 需要打开的网址 (例如 'https://www.google.com')
    :return: 执行结果消息
    """
    try:
        rpa = get_rpalite_instance()
        if rpa is None: raise RuntimeError("RPALite disabled")
        
        # 尝试 RPALite 中可能的浏览器相关方法
        if hasattr(rpa, 'open_browser'):
            rpa.open_browser(url)
        elif hasattr(rpa, 'open_website'):
            rpa.open_website(url)
        else:
            # 如果 RPALite 未提供显式方法，则回退到内置自带库
            raise NotImplementedError("RPALite 实例中没有找到明确的网页打开方法。")
            
        return f"已尝试使用 RPALite 打开网址: {url}"
        
    except Exception as e:
        # 后备方案：使用 Python 标准库 webbrowser
        import webbrowser
        try:
            webbrowser.open_new(url)
            return f"由于 RPALite 无法执行 ({str(e)})，已使用系统默认操作打开网址: {url}"
        except Exception as e2:
            return f"打开网址失败，RPALite 报错: {str(e)}，且系统 fallback 失败: {str(e2)}"

        
