import os
import uuid
# 移除全局直接导入 RPALite，改用动态获取，避免无 UI 环境直接崩溃
# from RPALite import RPALite
def get_rpalite_instance():
    try:
        # 延迟导入以避免无桌面环境下加载 GUI 库导致的阻断卡死
        from RPALite import RPALite
        return RPALite()
    except Exception as e:
        print(f"Warning: Failed to import/init RPALite: {e}")
        return None

def get_desktop_screenshot(save_dir=".", filename=None):
    """
    使用 RPALite 获取计算机桌面截图。
    :param save_dir: 截图保存的目录路径
    :param filename: 截图的名称，不带则自动生成UUID名称
    :return: 截图的完整文件路径
    """
    try:
        # 初始化 rpalite
        rpa = get_rpalite_instance()
        if rpa is None:
            raise NotImplementedError("RPALite 初始化失败，使用系统后备方案。")
        
        # 确保目录存在
        os.makedirs(save_dir, exist_ok=True)
        
        # 决定保存名称
        if not filename:
            filename = f"desktop_screenshot_{uuid.uuid4().hex[:8]}.png"
            
        full_path = os.path.join(save_dir, filename)
        
        # 尝试调用 RPALite 截图方法
        # RPALite.screenshot / capture / capture_screenshot 等常见API
        # 请根据具体安装的 RPALite 版本的方法进行准确调用
        if hasattr(rpa, 'screenshot'):
            rpa.screenshot(full_path)
        elif hasattr(rpa, 'capture_screenshot'):
            rpa.capture_screenshot(full_path)
        else:
            # Fallback
            rpa.capture(full_path)
            
        print(f"成功获取桌面截图，已保存至: {full_path}")
        return full_path
        
    except Exception as e:
        print(f"RPALite 截图获取失败: {str(e)}")
        
        # Fallback to standard Python cross-platform screenshot if rpalite isn't fully set up
        try:
            import pyautogui
            screenshot = pyautogui.screenshot()
            screenshot.save(full_path)
            print(f"改为使用 pyautogui 获取了截图: {full_path}")
            return full_path
        except Exception as e2:
            print(f"后备截图也失败了: {str(e2)}")
            return None

def open_windows_program(program_path, *args):
    """
    使用 RPALite 打开指定的 Windows 应用程序。
    :param program_path: 要打开的程序路径或命令 (例如 'notepad.exe', 'calc', 'C:\\Program Files\\...\\app.exe')
    :param args: 传递给程序的额外启动参数
    :return: 启动成功返回 True，否则返回 False
    """
    try:
        rpa = get_rpalite_instance()
        if rpa is None:
            raise NotImplementedError("RPALite 初始化失败，使用系统后备方案。")
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


def open_url_with_browser(url: str) -> str:
    """
    使用 RPALite (或后备系统方法) 在默认浏览器中打开指定的网页。
    :param url: 需要打开的网址 (例如 'https://www.google.com')
    :return: 执行结果消息
    """
    try:
        rpa = get_rpalite_instance()
        if rpa is None:
            raise NotImplementedError("RPALite 初始化失败，使用系统后备方案。")
        
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
