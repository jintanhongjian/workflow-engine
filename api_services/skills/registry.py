import datetime
import importlib
import os
import sys
import inspect
from google.genai import types
from docstring_parser import parse  # 推荐安装，用于解析参数说明

# 1. 自动发现配置
SKILLS_DIR = os.path.dirname(__file__)
# Helpers/utilities that should not be exposed as skills
IGNORE_FILES = ['__init__.py', 'registry.py', 'skill_template.py', 'ai_runtime_context.py']

class SkillRegistry:
    def __init__(self):
        self.functions_dict = {}  # 用于执行：{"func_name": func_obj}
        self.declarations = []    # 用于配置：[types.FunctionDeclaration, ...]
        self.openai_tools = []    # OpenAI 格式工具列表
        self._load_skills()

    def reload_skills(self):
        """Force reload all skills from the directory"""
        # Clear existing
        self.functions_dict = {}
        self.declarations = []
        self.openai_tools = []
        
        # Reload
        self._load_skills()
        return "Skills reloaded successfully"

    def _load_skills(self):
        """遍历文件夹动态导入所有 Python 函数"""
        for filename in os.listdir(SKILLS_DIR):
            if filename.endswith('.py') and filename not in IGNORE_FILES:
                module_name = f".{filename[:-3]}"
                full_module_name = f"api_services.skills.{filename[:-3]}"
                
                try:
                    # Check if module is already loaded
                    if full_module_name in sys.modules:
                         module = importlib.reload(sys.modules[full_module_name])
                    else:
                        # Dynamic import
                        module = importlib.import_module(module_name, package="api_services.skills")
                    
                    # 获取模块中定义的所有函数
                    for name, func in inspect.getmembers(module, inspect.isfunction):
                        # 判断是否是被 @register_skill 装饰的函数
                        if hasattr(func, '_is_skill') and func._is_skill is True:
                            self._register_function(name, func)
                except Exception as e:
                    print(f"Error loading skill {filename}: {e}")

    def _register_function(self, name, func):
        """核心逻辑：将 Python 函数转换为 Gemini 和 OpenAI 的工具声明"""
        # Remove older declarations to avoid duplicates when reloading or when modules share a name
        if name in self.functions_dict:
            self.declarations = [d for d in self.declarations if getattr(d, 'name', None) != name]
            self.openai_tools = [t for t in self.openai_tools if t.get('function', {}).get('name') != name]

        self.functions_dict[name] = func
        
        # 解析 Docstring 获取描述和参数说明
        doc = parse(inspect.getdoc(func) or "")
        sig = inspect.signature(func)
        
        # Gemini format properties
        properties = {}
        
        # OpenAI format properties
        openai_properties = {}
        
        required = []

        for param_name, param in sig.parameters.items():
            # 查找 docstring 中对应的参数描述
            param_doc = next((p.description for p in doc.params if p.arg_name == param_name), "")
            
            # 映射 Python 类型到 JSON Schema 类型
            # 默认为 STRING，可以根据类型注解扩展
            gemini_type = "STRING"
            openai_type = "string"
            
            if param.annotation == int: 
                gemini_type = "INTEGER"
                openai_type = "integer"
            elif param.annotation == float: 
                gemini_type = "NUMBER"
                openai_type = "number"
            elif param.annotation == bool: 
                gemini_type = "BOOLEAN"
                openai_type = "boolean"

            # Build Gemini Property
            properties[param_name] = types.Schema(
                type=gemini_type,
                description=param_doc or f"Parameter {param_name}"
            )
            
            # Build OpenAI Property
            openai_properties[param_name] = {
                "type": openai_type,
                "description": param_doc or f"Parameter {param_name}"
            }
            
            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        # 构建 Gemini 声明
        declaration = types.FunctionDeclaration(
            name=name,
            description=doc.short_description or "No description provided",
            parameters=types.Schema(
                type="OBJECT",
                properties=properties,
                required=required
            )
        )
        self.declarations.append(declaration)

        # 构建 OpenAI 声明
        openai_declaration = {
            "type": "function",
            "function": {
                "name": name,
                "description": doc.short_description or "No description provided",
                "parameters": {
                    "type": "object",
                    "properties": openai_properties,
                    "required": required
                }
            }
        }
        self.openai_tools.append(openai_declaration)

    def get_skill_details(self, skill_name):
        """Get detailed skill information for UI consumption."""
        for tool in self.openai_tools:
            func_data = tool.get('function', {})
            if func_data.get('name') == skill_name:
                params_obj = func_data.get('parameters', {})
                props = params_obj.get('properties', {})
                required_list = params_obj.get('required', [])
                
                param_list = []
                for p_name, p_info in props.items():
                    param_list.append({
                        'name': p_name,
                        'type': p_info.get('type', 'string'),
                        'description': p_info.get('description', ''),
                        'required': p_name in required_list
                    })
                
                return {
                    'name': skill_name,
                    'description': func_data.get('description', ''),
                    'parameters': param_list
                }
        return None

    def get_gemini_tool(self):
        """获取最终给 Gemini 客户端使用的 Tool 对象"""
        return types.Tool(function_declarations=self.declarations)

    def get_openai_tools(self):
        """获取最终给 OpenAI 客户端使用的 tools 列表"""
        return self.openai_tools

# 单例模式实例化
registry = SkillRegistry()
