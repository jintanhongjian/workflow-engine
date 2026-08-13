import subprocess
import os
import sys
import importlib
import traceback
import datetime
import re
import time
import random
from pathlib import Path
from functools import wraps
from .decorators import retry_on_429, register_skill

# Try to import GenAI and Settings
try:
    from google import genai
    from google.genai import types
    from django.conf import settings
except ImportError:
    pass


def _clean_code_block(text: str) -> str:
    """Extract code from markdown code blocks if present."""
    match = re.search(r"```python\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    return text


def _normalize_requirements(raw_requirements: str) -> str:
    if not raw_requirements:
        return ""

    marker_tokens = {
        'CODE_START', 'CODE_END', 'TEST_START', 'TEST_END',
        'FILENAME:', 'REQUIREMENTS:',
    }
    normalized_tokens = []
    for token in raw_requirements.split():
        t = token.strip().strip(',')
        if not t:
            continue
        if t.upper() in marker_tokens:
            continue
        if t.lower() in {'none', 'n/a', 'na', 'null'}:
            continue
        normalized_tokens.append(t)
    return " ".join(normalized_tokens)


SECURITY_FORBIDDEN_PATTERNS = [
    (r"\bos\.remove\s*\(", "禁止删除文件: os.remove"),
    (r"\bos\.unlink\s*\(", "禁止删除文件: os.unlink"),
    (r"\bshutil\.rmtree\s*\(", "禁止删除目录: shutil.rmtree"),
    (r"\bPath\s*\([^)]*\)\.unlink\s*\(", "禁止删除文件: pathlib.Path.unlink"),
    (r"\bos\.system\s*\(", "禁止系统命令执行: os.system"),
    (r"\bos\.popen\s*\(", "禁止系统命令执行: os.popen"),
    (r"\bsubprocess\.(run|Popen|call|check_call|check_output)\s*\(", "禁止系统命令执行: subprocess"),
    (r"\bkill\s*-\d+", "禁止进程控制命令: kill"),
    (r"\bpkill\b", "禁止进程控制命令: pkill"),
    (r"\bkillall\b", "禁止进程控制命令: killall"),
    (r"\btaskkill\b", "禁止进程控制命令: taskkill"),
    (r"\brm\s+-rf\b", "禁止危险删除命令: rm -rf"),
    (r"\bsudo\b", "禁止提权命令: sudo"),
]


MODEL_SELECTION_CACHE_TTL_SECONDS = 600
_MODEL_SELECTION_CACHE: dict[str, str | float | None] = {
    'model': None,
    'purpose': None,
    'expires_at': 0,
}


def _select_generation_model(default_model: str, default_purpose: str = 'coding') -> str:
    purpose = (os.getenv('MODEL_SELECT_PURPOSE', default_purpose) or default_purpose).strip().lower()
    now = time.time()

    cached_model = _MODEL_SELECTION_CACHE.get('model')
    cached_purpose = _MODEL_SELECTION_CACHE.get('purpose')
    cached_expires_at = float(_MODEL_SELECTION_CACHE.get('expires_at') or 0)
    if cached_model and cached_purpose == purpose and now < cached_expires_at:
        return str(cached_model)

    try:
        from api_services.check_models import auto_select_model, list_gemini_models

        model_results = list_gemini_models(purpose=purpose, verbose=False)
        recommendation = auto_select_model(model_results, purpose=purpose)
        selected_model = (recommendation or {}).get('model')
        if selected_model:
            _MODEL_SELECTION_CACHE['model'] = selected_model
            _MODEL_SELECTION_CACHE['purpose'] = purpose
            _MODEL_SELECTION_CACHE['expires_at'] = now + MODEL_SELECTION_CACHE_TTL_SECONDS
            print(f"Auto-selected Gemini model for purpose '{purpose}': {selected_model}")
            return selected_model
    except Exception as e:
        print(f"Warning: auto model selection failed, fallback to '{default_model}': {e}")

    return default_model


def _find_security_violations(source: str, label: str) -> list[str]:
    violations = []
    if not source:
        return violations

    for pattern, reason in SECURITY_FORBIDDEN_PATTERNS:
        if re.search(pattern, source, flags=re.IGNORECASE):
            violations.append(f"{label}: {reason}")
    return violations


def _validate_skill_filename(filename: str, skills_dir: str) -> str | None:
    if not filename:
        return "Invalid filename: empty"

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.py", filename):
        return "Invalid filename: only letters, numbers, underscore are allowed (must end with .py)"

    skills_root = Path(skills_dir).resolve()
    target = (skills_root / filename).resolve()
    if skills_root not in target.parents and target != skills_root:
        return "Invalid filename: path traversal detected"

    return None


def _enforce_skill_security_policy(code: str, test_code: str, filename: str, skills_dir: str) -> list[str]:
    violations = []

    filename_error = _validate_skill_filename(filename, skills_dir)
    if filename_error:
        violations.append(filename_error)

    violations.extend(_find_security_violations(code, "Generated code"))
    violations.extend(_find_security_violations(test_code, "Generated test"))
    return violations

@retry_on_429(max_retries=3, initial_delay=5)
def _fix_code_with_ai(code: str, error: str, test_code: str = None) -> str:
    """Uses Gemini to fix broken code based on error message."""
    try:
        try:
            from api_services.models import APIKey
            api_key = APIKey.objects.get(name='Gemini JT').key
        except:
            api_key = getattr(settings, 'GEMINI_API_KEY', None)
        
        if not api_key:
            print("Warning: GEMINI_API_KEY not found in settings, cannot auto-fix code.")
            return None
            
        client = genai.Client(api_key=api_key)
        
        prompt = f"The following Python code needs to be fixed because it raised an error during validation/testing.\n"
        prompt += f"ERROR:\n{error}\n\n"
        if test_code:
            prompt += f"TEST CODE THAT FAILED:\n{test_code}\n\n"
        prompt += f"BROKEN CODE:\n{code}\n\n"
        prompt += "Please fix the code to resolve the error. Ensure it is a valid, complete Python module.\n"
        prompt += "CRITICAL: Ensure the fixed code imports `register_skill` from `api_services.skills.registry` and decorates the main function with `@register_skill`.\n"
        prompt += "Return ONLY the Python code. Do not include markdown formatting or explanations."
        
        selected_model = _select_generation_model(default_model="models/gemini-2.5-flash", default_purpose='coding')
        response = client.models.generate_content(
            model=selected_model,
            contents=prompt
        )
        
        if response.text:
            return _clean_code_block(response.text)
            
    except Exception as e:
        print(f"AI Fix failed: {e}")
        
    return None

@retry_on_429(max_retries=3, initial_delay=5)
def _generate_code_from_description(description: str) -> tuple[str, str, str, str]:
    """Generates Python code, test code, filename, and requirements from a natural language description."""
    try:
        try:
            from api_services.models import APIKey
            api_key = APIKey.objects.get(name='Gemini JT').key
        except:
            api_key = getattr(settings, 'GEMINI_API_KEY', None)

        if not api_key:
            print("Warning: GEMINI_API_KEY not found in settings.")
            return None, None, None, None
            
        client = genai.Client(api_key=api_key)
        
        prompt = f"""
        You are an expert Python developer. I need you to create a new "skill" (a standalone Python module with a specific function) based on the requirement below.

        REQUIREMENT:
        {description}

        INSTRUCTIONS:
        1. DESIGN a suitable python filename for this skill (must end in .py).
        2. IDENTIFY any 3rd party PyPI packages needed (space separated).
        3. WRITE the implementation code:
            - **MUST import `register_skill` from `api_services.skills.registry`.**
            - **MUST apply the `@register_skill` decorator to the main function.**
            - Must be valid Python, include docstrings and type hints.
        4. WRITE a test script to verify the function works.

        RESPONSE FORMAT:
        FILENAME: <your_filename.py>
        REQUIREMENTS: <package1 package2 ...>
        CODE_START
        ... (Your Python implementation code) ...
        CODE_END
        TEST_START
        ... (Your Python test code) ...
        TEST_END
        """
        selected_model = _select_generation_model(default_model="models/gemini-2.0-flash", default_purpose='coding')
        response = client.models.generate_content(
            model=selected_model,
            contents=prompt
        )
        
        if not response.text:
            return None, None, None, None

        text = response.text
        
        # Parse output using more robust regex to handle potential formatting variations
        filename_match = re.search(r"FILENAME:\s*(.+?)\s*$", text, re.MULTILINE)
        requirements_match = re.search(r"REQUIREMENTS:\s*(.*?)\s*$", text, re.MULTILINE)
        code_match = re.search(r"CODE_START\s*(.*?)\s*CODE_END", text, re.DOTALL)
        test_match = re.search(r"TEST_START\s*(.*?)\s*TEST_END", text, re.DOTALL)
        
        # Helper to get group content safely
        def get_group(match, default=None):
            return match.group(1).strip() if match else default

        filename = get_group(filename_match, "generated_skill.py")
        requirements = _normalize_requirements(get_group(requirements_match, ""))
        code = get_group(code_match, None)
        test_code = get_group(test_match, None)
        
        if not code:
            code = _clean_code_block(text)

        test_code = _clean_code_block(test_code) if test_code else None
            
        return code, test_code, filename, requirements

    except Exception as e:
        print(f"Code Generation failed: {e}")
        return None, None, None, None

@register_skill
def fix_skill_at_runtime(skill_name: str, error_trace: str, args: dict = None) -> str:
    """
    Attempts to fix a skill that failed at runtime using AI.
    
    :param skill_name: The name of the function that failed.
    :param error_trace: The traceback string of the exception.
    :param args: The arguments passed to the function when it failed.
    :return: A status message indicating success or failure.
    """
    try:
        # 1. Locate the file
        import inspect  # Ensure inspect is available
        from api_services.skills.registry import registry
        
        # Find the function in the registry to get its details
        func_obj = registry.functions_dict.get(skill_name)
        if not func_obj:
            return f"Error: Skill '{skill_name}' not found in registry."
            
        # Get the module to find the filename
        module = inspect.getmodule(func_obj)
        if not module:
             return f"Error: Could not determine module for skill '{skill_name}'."
             
        file_path = module.__file__
        if not file_path or not os.path.exists(file_path):
             return f"Error: Source file for skill '{skill_name}' not found at {file_path}."

        print(f"Attempting to fix runtime error in '{skill_name}' ({file_path})...")

        # 2. Read the source code
        with open(file_path, 'r', encoding='utf-8') as f:
            current_code = f.read()

        # 3. Construct prompt for AI
        prompt = f"""
        The Python function `{skill_name}` failed at runtime.
        Please fix the code based on the error traceback and the arguments provided.

        **Source File**: {file_path}
        **Arguments**: {args}
        **Error Traceback**:
        {error_trace}

        **Current Code**:
        ```python
        {current_code}
        ```

        **Instructions**:
        1. Analyze the error.
        2. Fix the code to handle the edge case or error condition.
        3. Keep the same function signature if possible (unless the signature itself is the problem).
        4. Return ONLY the full corrected Python code for the entire file.
        5. Ensure all imports are present.
        6. **IMPORTANT**: Ensure the `@register_skill` decorator is still applied to the main function and `register_skill` is imported.
        """
        
        # 4. Call AI to fix it
        try:
            from api_services.models import APIKey
            gem_api_key = APIKey.objects.get(name='Gemini JT').key
        except:
            gem_api_key = str(settings.GEMINI_API_KEY).strip()
        client = genai.Client(api_key=gem_api_key)
        
        selected_model = _select_generation_model(default_model="models/gemini-2.5-flash", default_purpose='coding')
        response = client.models.generate_content(
            model=selected_model,
            contents=prompt
        )
        
        if not response.text:
            return "Error: AI returned empty response for fix."
            
        fixed_code = _clean_code_block(response.text)
        
        # 5. Backup existing file
        backup_path = f"{file_path}.bak"
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(current_code)
            
        # 6. Write new code
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(fixed_code)
            
        # 7. syntax check
        try:
            compile(fixed_code, file_path, 'exec')
        except SyntaxError as e:
            # Restore backup if syntax is invalid
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(current_code)
            return f"AI Fix Failed: Generated code has syntax errors: {e}"

        # 8. Reload registry
        registry.reload_skills()
        
        # 9. Update documentation for the fixed skill
        try:
            generate_skill_documentation(target_skill_name=skill_name)
            doc_msg = " Documentation regenerated successfully."
        except Exception as doc_err:
            doc_msg = f" Failed to regenerate documentation: {doc_err}"
        
        return f"Success: Skill '{skill_name}' patched and reloaded. Backup at {backup_path}.{doc_msg}"

    except Exception as e:
        return f"Critical error during runtime fix: {traceback.format_exc()}"

@register_skill
def create_and_register_skill(description: str, max_retries: int = 5):
    """
    根据自然语言描述自动生成、验证并在系统中注册（用@register_skill装饰器）一个新的 Python 技能。
    
    :param description: 技能的详细功能描述。AI 将根据此描述推断文件名、安装依赖、生成代码和测试用例。
    :param max_retries: 最大尝试修复代码的次数。
    """
    # 延迟导入以避免循环引用
    try:
        from api_services.skills.registry import registry
    except ImportError:
        # Fallback absolute import
        from api_services.skills.registry import registry

    skills_dir = os.path.dirname(__file__)
    
    # 0. 根据描述生成代码、文件名和依赖
    print(f"Analyzing requirements and generating code...")
    code, test_code, filename, requirements = _generate_code_from_description(description)
    
    if not code:
        return "Error: Failed to generate code from description."
        
    print(f"Plan: Create '{filename}' with dependencies: '{requirements}'")

    if not filename.endswith('.py'):
        filename += ".py"
        
    if os.path.sep in filename or (os.path.altsep and os.path.altsep in filename):
        # Sanitize filename to strict base name
        filename = os.path.basename(filename)

    policy_violations = _enforce_skill_security_policy(code, test_code, filename, skills_dir)
    if policy_violations:
        return "Security policy violation:\n- " + "\n- ".join(policy_violations)

    file_path = os.path.join(skills_dir, filename)

    # 1. 安装依赖
    if requirements and requirements.lower() != "none" and requirements.strip():
        print(f"Installing requirements: {requirements}")
        reqs = requirements.split()
        
        # Determine installation method based on environment
        # If running via 'uv run', we might be in an ephemeral venv or main venv. 
        # But 'uv pip install' is generally safer if uv is available.
        # However, fallback to 'pip install' within the current python executable is most compatible.
        
        install_methods = [
            # 1. Try 'uv pip install' (fastest if uv is available and venv is active)
            ["uv", "pip", "install"] + reqs,
            # 2. Try standard 'pip install' with current python
            [sys.executable, "-m", "pip", "install"] + reqs,
        ]

        success = False
        last_error = ""

        for cmd in install_methods:
            try:
                # Use subprocess.PIPE to capturing output to debug but not show unless error
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"Successfully installed requirements using {' '.join(cmd[:3])}")
                    success = True
                    break
                else:
                    last_error = result.stderr
            except FileNotFoundError:
                continue # Command not found (e.g. 'uv')
        
        if not success:
            # 3. Final fallback: sudo pip install
            print(f"Non-privileged install failed. Trying sudo... Last error: {last_error}")
            sudo_cmd = ["sudo", sys.executable, "-m", "pip", "install"] + reqs
            sudo_result = subprocess.run(sudo_cmd, capture_output=True, text=True)
            if sudo_result.returncode != 0:
                return f"Failed to install requirements with sudo: {sudo_result.stderr}"
            print("Successfully installed requirements with sudo.")

    # 2. 循环尝试写入、验证和修正
    current_code = code
    last_error = ""

    for attempt in range(max_retries + 1):
        # 尝试写入文件
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(current_code)
        except PermissionError:
            # 尝试使用 sudo 写入
            print("Permission denied, using sudo to write file...")
            proc = subprocess.Popen(['sudo', 'tee', file_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = proc.communicate(input=current_code.encode('utf-8'))
            if proc.returncode != 0:
                return f"Failed to write file with sudo: {err.decode('utf-8')}"
        except Exception as e:
            return f"Error writing file: {str(e)}"

        # 3. 验证代码 (语法检查)
        syntax_error = None
        try:
            compile(current_code, file_path, 'exec')
        except SyntaxError as e:
            syntax_error = f"Syntax Error in generated code: {e}"
        
        # 4. 运行测试 (如果语法正确且提供测试代码)
        test_error = None
        if not syntax_error and test_code:
            test_file_path = os.path.join(skills_dir, f"test_{filename}")
            # Need project root in path to import api_services.skills
            project_root = os.path.dirname(os.path.dirname(skills_dir))
            full_test_code = f"import sys\nsys.path.append('{project_root}')\nfrom api_services.skills import {filename[:-3]}\n\n" + test_code
            
            try:
                with open(test_file_path, 'w') as f:
                    f.write(full_test_code)
                
                # 运行测试
                test_result = subprocess.run([sys.executable, test_file_path], capture_output=True, text=True, timeout=10)
                
                if test_result.returncode != 0:
                    test_error = f"Test failed: {test_result.stderr}\nOutput: {test_result.stdout}"
                    
            except Exception as e:
                test_error = f"Error running test: {str(e)}"
            finally:
                # 清理测试文件
                if os.path.exists(test_file_path):
                    os.remove(test_file_path)

        # 检查结果
        if not syntax_error and not test_error:
            # 成功！
            break
        
        # 记录错误
        last_error = syntax_error or test_error
        
        # 如果还有重试机会，尝试使用 AI 修复
        if attempt < max_retries:
            print(f"Attempt {attempt+1}/{max_retries+1} failed: {last_error}")
            print("Requesting AI fix...")
            
            fixed_code = None
            try:
                # 尝试导入修复函数（如果是内部调用，直接用；这里是本模块函数）
                fixed_code = _fix_code_with_ai(current_code, last_error, test_code)
            except Exception as e:
                 print(f"Failed to invoke AI fix: {e}")

            if fixed_code:
                fixed_violations = _enforce_skill_security_policy(fixed_code, test_code, filename, skills_dir)
                if fixed_violations:
                    return "Security policy violation after AI fix:\n- " + "\n- ".join(fixed_violations)
                print("AI suggested a fix. Applying...")
                current_code = fixed_code
                continue
            else:
                print("AI returned no fix or failed. Aborting retries.")
                break
    else:
        # 循环结束仍未成功（else 对应 for 正常结束即所有重试都失败）
        # 删除错误文件以免影响 registry
        try:
            os.remove(file_path)
        except Exception:
            pass
        return f"Failed to create skill after {max_retries} retries. Last Error: {last_error}"

    # 5. 重载 Registry
    try:
        # 调用 registry 的重载方法
        # 注意：在某些环境下 registry 实例可能是单例，需要确保我们操作的是同一个实例
        # 这里我们在本模块导入了 registry，通常是同一个对象
        registry.reload_skills()
        
        # 验证新技能是否已注册 (双重检查)
        # 获取模块名 (去掉 .py)
        module_name = filename[:-3]
        # 我们无法直接知道函数名，但我们可以检查 module 是否被加载
        if f"api_services.skills.{module_name}" not in sys.modules:
             return f"Warning: File written but module 'api_services.skills.{module_name}' not loaded in sys.modules."

        # 修改：创建成功后自动补全并更新文档 (仅更新新增的部分)
        try:
            generate_skill_documentation(target_skill_name=filename[:-3]) 
            doc_msg = " Documentation regenerated successfully."
        except Exception as doc_err:
            doc_msg = f" Failed to regenerate documentation: {doc_err}"

        return f"Success: Skill '{filename}' created, dependencies installed, validated, and registered.{doc_msg}"
        
    except Exception as e:
        return f"Error reloading registry: {traceback.format_exc()}"

@register_skill
def execute_sudo_command(command: str, password: str = None):
    """
    使用 sudo 执行任意系统命令。请谨慎使用。
    :param command: Shell 命令
    :param password: sudo 密码 (可选)
    """
    try:
        if password:
            # Use sudo -S to accept password from stdin
            # Ensure command is run with shell=True if it contains shell features (pipes, etc)
            # but sudo -S needs to be the first part.
            # If using shell=True, we can pass input to the shell process.
            cmd_str = f"sudo -S {command}"
            result = subprocess.run(
                cmd_str, 
                input=f"{password}\n", 
                shell=True, 
                capture_output=True, 
                text=True
            )
        else:
            result = subprocess.run(f"sudo {command}", shell=True, capture_output=True, text=True)
            
        return f"Exit Code: {result.returncode}\nStdout: {result.stdout}\nStderr: {result.stderr}"
    except Exception as e:
        return f"Execution failed: {str(e)}"

@register_skill
def generate_skill_documentation(output_dir: str = "skills_docs", target_skill_name: str = None):
    """
    生成所有已注册技能的 Markdown 文档，每个技能生成一个单独的文件，文件名为技能函数名。
    如果提供了 target_skill_name，则只生成指定技能的文档，并更新目录文档。
    
    :param output_dir: 文档输出目录，默认为项目根目录下的 skills_docs
    :param target_skill_name: 指定的技能名称
    """
    # 延迟导入
    try:
        from api_services.skills.registry import registry
    except ImportError:
        # Fallback absolute import
        from api_services.skills.registry import registry
        
    registry.reload_skills()
    tools = registry.get_openai_tools()
    
    try:
        if not os.path.isabs(output_dir):
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(current_dir))
            output_dir = os.path.join(project_root, output_dir)
            
        os.makedirs(output_dir, exist_ok=True)
        
        tools_to_process = tools
        if target_skill_name:
            tools_to_process = [t for t in tools if t.get('function', {}).get('name') == target_skill_name]
            if not tools_to_process:
                return f"Error: Skill '{target_skill_name}' not found."

        generated_files = []
        for tool in tools_to_process:
            func_info = tool.get('function', {})
            name = func_info.get('name', 'Unknown')
            description = func_info.get('description', 'No description')
            parameters = func_info.get('parameters', {})
            
            markdown_content = [f"# `{name}`\n"]
            markdown_content.append(f"*(Generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})*\n")
            
            func_obj = registry.functions_dict.get(name)
            if func_obj:
                module_path = getattr(func_obj, '__module__', 'Unknown Module')
                markdown_content.append(f"**Import Path**: `from {module_path} import {name}`\n")
            
            markdown_content.append(f"{description}\n")
            
            if 'properties' in parameters and parameters['properties']:
                markdown_content.append("### Parameters\n")
                markdown_content.append("| Parameter | Type | Description | Required |")
                markdown_content.append("| :--- | :--- | :--- | :--- |")
                
                required_params = func_info.get('parameters', {}).get('required', [])
                
                for param_name, param_info in parameters['properties'].items():
                    p_type = param_info.get('type', 'string')
                    p_desc = param_info.get('description', '')
                    is_req = "✅ Yes" if param_name in required_params else "No"
                    markdown_content.append(f"| `{param_name}` | *{p_type}* | {p_desc} | {is_req} |")
            
            file_path = os.path.join(output_dir, f"{name}.md")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(markdown_content))
                
            short_desc = description.strip().split('\n')[0] if description else "No description"
            generated_files.append({"name": name, "file": f"{name}.md", "description": short_desc})
            
        catalog_path = os.path.join(output_dir, "SKILLS_CATALOG.md")
        
        if target_skill_name and os.path.exists(catalog_path):
            with open(catalog_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            new_item = generated_files[0]
            new_line = f"- [{new_item['name']}](./{new_item['file']}) - {new_item['description']}\n"
            
            replaced = False
            for i, line in enumerate(lines):
                if line.startswith(f"- [{new_item['name']}]("):
                    lines[i] = new_line
                    replaced = True
                    break
            
            if not replaced:
                lines.append(new_line)
                
            with open(catalog_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
        else:
            catalog_content = ["# AI Skills Catalog\n"]
            catalog_content.append(f"*(Generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})*\n")
            catalog_content.append("This catalog lists all available skills and their documentation paths. Use these links to find detailed parameters and usage instructions.\n")
            
            # Use all tools to build full catalog if doing full run or missing catalog
            for tool in tools:
                t_name = tool.get('function', {}).get('name', 'Unknown')
                t_desc = tool.get('function', {}).get('description', 'No description').strip().split('\n')[0]
                catalog_content.append(f"- [{t_name}](./{t_name}.md) - {t_desc}")
                
            with open(catalog_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(catalog_content))
            
        return f"Documentation and catalog generated successfully for {len(generated_files)} skills at: {output_dir}"
    except Exception as e:
        return f"Failed to generate documentation: {str(e)}"

@register_skill
def read_skill_documentation(skill_name: str) -> str:
    """
    读取指定已有技能(skill)的详细 Markdown 说明文档。
    如果需要在调用已有技能之前了解详情和使用方法，请先调用此任务。
    
    :param skill_name: 技能名称，需要与目录内的名称一致
    """
    try:
        from django.conf import settings
        if hasattr(settings, 'BASE_DIR'):
            doc_path = os.path.join(settings.BASE_DIR, 'skills_docs', f"{skill_name}.md")
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(current_dir))
            doc_path = os.path.join(project_root, 'skills_docs', f"{skill_name}.md")
            
        if os.path.exists(doc_path):
            with open(doc_path, 'r', encoding='utf-8') as f:
                return f.read()
        return f"Warning: Documentation for skill '{skill_name}' not found at {doc_path}."
    except Exception as e:
        return f"Error reading skill documentation: {str(e)}"
