import os
import traceback
from google import genai
from google.genai import types
from django.conf import settings
from .skills.registry import registry
from .skills.ai_runtime_context import set_current_user, reset_current_user
from .models import SkillExecutionLog, APIKey, SystemPrompt, ConversationMode
from .check_models import get_recommended_model_name

def _resolve_mode_prompt(conversation_mode_code: str):
    """Return a SystemPrompt text from ConversationMode default if available."""
    try:
        mode_obj = (
            ConversationMode.objects
            .filter(code=conversation_mode_code, is_active=True)
            .select_related('default_system_prompt')
            .first()
        )
        if mode_obj and mode_obj.default_system_prompt:
            sp = mode_obj.default_system_prompt
            return "\n".join([
                f"角色：{sp.role_name}",
                f"角色定义：{sp.role_definition}",
                f"提示词：{sp.prompt_content}",
            ])
    except Exception as e:
        print(f"Resolve mode prompt failed for {conversation_mode_code}: {e}")
    return None

def _get_purpose_from_mode(conversation_mode_code: str):
    """Helper to get purpose string from ConversationMode, used for model recommendation."""
    try:
        mode_obj = ConversationMode.objects.filter(code=conversation_mode_code, is_active=True).first()
        if mode_obj and mode_obj.purpose:
            return mode_obj.purpose
    except Exception as e:
        print(f"Get purpose from mode failed for {conversation_mode_code}: {e}")
    return None

def run_intelligent_task(user_prompt, sys_config=None, tools=None, 
                         documents=None, current_user=None, 
                         debug=False, on_log=None, conversation_mode: str = 'run_intelligent_task',
                         purpose: str = None, max_turns=10, auto_fix_retry=5):
    """
    运行智能任务，支持多轮工具调用和动态技能生成。
    当 debug=True 时，收集关键步骤日志并随结果返回。
    """
    logs: list[str] = []

    def log(msg: str):
        msg_str = str(msg)
        logs.append(msg_str)
        print(msg_str)
        if callable(on_log):
            try:
                on_log(msg_str)
            except Exception:
                pass
    # 1. 配置 API
    try:
        gem_api_key = APIKey.objects.get(name='Gemini JT').key
    except Exception:
        gem_api_key = getattr(settings, 'GEMINI_API_KEY', '')
    gem_api_key = str(gem_api_key).strip()
    client = genai.Client(api_key=gem_api_key)
    log(f"Init Gemini client (key set={bool(gem_api_key)}).")

    # 将当前用户注入上下文，便于技能函数获取创建者
    token = set_current_user(current_user)

    if not sys_config:
        sys_config = _resolve_mode_prompt(conversation_mode) or sys_config
    
    final_sys_config = str(sys_config or "")
    
    # 调阅 SKILLS_CATALOG.md，提供给 AI 以决定是调用现有技能还是创建新技能
    catalog_path = getattr(settings, 'SKILLS_CATALOG_PATH', None)
    if catalog_path and os.path.exists(catalog_path):
        try:
            with open(catalog_path, 'r', encoding='utf-8') as f:
                catalog_content = f.read()
            skill_guidance = (
                "\n\n--- Available Skills Catalog ---\n"
                f"{catalog_content}\n"
                "----------------------------------\n"
                "Instructions:\n"
                "1. Please carefully read the Available Skills Catalog above.\n"
                "2. If an existing skill can fulfill the user's requirement, you SHOULD first call `read_skill_documentation` to get its accurate parameters list, and then naturally call the target skill in the next turn.\n"
                "3. If there is NO existing skill that can fulfill the requirement, you MUST use the `create_and_register_skill` tool to create a new one first, then you can call it."
            )
            final_sys_config += skill_guidance
        except Exception as e:
            log(f"Warning: Failed to read skills catalog: {e}")

    if not purpose:
        purpose = _get_purpose_from_mode(conversation_mode) or 'general'
    # 构造消息部分
    user_parts = [types.Part(text=user_prompt)]
    
    # 处理文档上传
    if documents:
        try:
            for doc in documents:
                if os.path.exists(doc.file.path):
                    log(f"Uploading file for intelligent task: {doc.file.path}")
                    sample_file = client.files.upload(file=doc.file.path)
                    user_parts.append(types.Part.from_uri(
                        file_uri=sample_file.uri,
                        mime_type=sample_file.mime_type
                    ))
                else:
                    log(f"Warning: File not found {doc.file.path}")
        except Exception as e:
            log(f"Error uploading file in run_intelligent_task: {e}")

    # 初始消息历史
    messages = [types.Content(role="user", parts=user_parts)]

    try:
        current_turn = 0
        while current_turn < max_turns:
            current_turn += 1
            
            # 每次循环都重新获取工具列表，因为 create_and_register_skill 可能更新了 registry
            # 如果传入了 tools (静态指定)，则使用传入的；否则使用 registry (动态)
            current_tools = tools if tools is not None else [registry.get_gemini_tool()]

            response = None
            excluded_models = []
            last_error = None

            # 尝试最多 3 次模型回退
            for model_attempt in range(3):
                try:
                    # 动态选择模型 (排除已失败的)
                    model_name = get_recommended_model_name(purpose=purpose, excluded_models=excluded_models, api_key=gem_api_key)
                    log(f"Generate Content using: {model_name} (Turn {current_turn}, Attempt {model_attempt+1})")

                    # 生成回复
                    response = client.models.generate_content(
                        model=model_name, # 动态
                        contents=messages,
                        config=types.GenerateContentConfig(
                            system_instruction=final_sys_config, 
                            tools=current_tools
                        )
                    )
                    break 
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    if '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str:
                        log(f"⚠️ Model {model_name} quota exhausted. Switching model...")
                        excluded_models.append(model_name)
                        import time
                        time.sleep(2)
                    else:
                        if debug:
                            return {"text": f"Error communicating with Gemini: {str(e)}", "logs": logs}
                        return f"Error communicating with Gemini: {str(e)}"
            
            if not response:
                err_txt = f"Error: Failed to generate content after retries. Last error: {str(last_error)}"
                if debug:
                    return {"text": err_txt, "logs": logs}
                return err_txt

            # 检查响应有效性
            if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
                err_txt = "Error: Empty response from model."
                return {"text": err_txt, "logs": logs} if debug else err_txt
                
            first_content = response.candidates[0].content
            
            # 检查是否有工具调用
            has_tool_call = False
            for part in first_content.parts:
                if part.function_call:
                    has_tool_call = True
                    break
                    
            # 如果没有工具调用，说明任务完成，返回最终文本
            if not has_tool_call:
                return {"text": response.text, "logs": logs} if debug else response.text

            # 如果有工具调用，将模型的思考过程加入历史
            messages.append(first_content)
            
            # 处理所有工具调用
            tool_response_parts = []
            for part in first_content.parts:
                if part.function_call:
                    name = part.function_call.name
                    args = part.function_call.args
                    
                    log(f"--- 🚀 Turn {current_turn}: 调用技能 {name} ---")
                    
                    # 查找函数
                    # 注意：registry.reload_skills() 可能在 create_and_register_skill 中被调用
                    # 所以我们总是从 registry.functions_dict 获取最新函数
                    func = registry.functions_dict.get(name)
                    
                    result = None
                    log_args = args if isinstance(args, dict) else {"args": str(args)}

                    if func:
                        # 尝试执行，如果出错则自动修复并重试 (最多重试 auto_fix_retry 次)
                        for attempt in range(auto_fix_retry + 1):
                            try:
                                # 重新获取函数引用，因为修复后函数对象会改变
                                if attempt > 0:
                                    func = registry.functions_dict.get(name)
                                    if not func:
                                        result = f"Error: Function {name} disappeared after reload."
                                        break
                                        
                                # 执行函数
                                if isinstance(args, dict):
                                     result = func(**args)
                                else:
                                     result = func() # 无参调用
                                
                                # 记录成功日志
                                try:
                                    SkillExecutionLog.objects.create(
                                        skill_name=name,
                                        arguments=log_args,
                                        status="SUCCESS",
                                        result_summary=str(result)[:1000]
                                    )
                                except Exception as log_err:
                                    log(f"Warning: Failed to log execution: {log_err}")

                                # 如果成功执行，跳出重试循环
                                break
                                
                            except Exception as e:
                                error_msg = str(e)
                                log(f"Error executing {name} (Attempt {attempt+1}/{auto_fix_retry+1}): {e}")
                                
                                # 如果还有重试机会，尝试修复
                                if attempt < auto_fix_retry:
                                    log(f"Attempting auto-fix for {name} (Fix attempt {attempt+1})...")
                                    try:
                                        from api_services.skills.root_skill_manager import fix_skill_at_runtime
                                        fix_msg = fix_skill_at_runtime(name, traceback.format_exc(), args)
                                        log(f"Auto-fix output: {fix_msg}")
                                        
                                        if "Success" in fix_msg:
                                            # 记录修复日志
                                            try:
                                                SkillExecutionLog.objects.create(
                                                    skill_name=name,
                                                    arguments=log_args,
                                                    status="AUTO-FIXED",
                                                    error_message=traceback.format_exc(),
                                                    result_summary=fix_msg
                                                )
                                            except: pass

                                            # 修复成功，进入下一次循环重试
                                            continue
                                        else:
                                            # 修复失败，记录错误并退出
                                            try:
                                                SkillExecutionLog.objects.create(
                                                    skill_name=name,
                                                    arguments=log_args,
                                                    status="FAILED",
                                                    error_message=f"{error_msg}\nFix failed: {fix_msg}"
                                                )
                                            except: pass

                                            result = f"Error executing {name}: {e}\nAuto-fix failed: {fix_msg}"
                                            break
                                    except Exception as fix_err:
                                        log(f"Auto-fix system failed: {fix_err}")
                                        result = f"Error executing {name}: {e}\nAuto-fix system error: {fix_err}"
                                        break
                                else:
                                    # 重试次数用尽仍然失败
                                    try:
                                        SkillExecutionLog.objects.create(
                                            skill_name=name,
                                            arguments=log_args,
                                            status="FAILED",
                                            error_message=traceback.format_exc()
                                        )
                                    except: pass
                                    result = f"Error executing {name} after auto-fix: {traceback.format_exc()}"
                    else:
                        result = f"Error: Function {name} not found locally."
                        log(result)
                    
                    # 构造响应
                    tool_response_parts.append(
                        types.Part.from_function_response(
                            name=name,
                            response={"result": result}
                        )
                    )

            # 将工具执行结果加入历史，进入下一轮循环
            if tool_response_parts:
                messages.append(types.Content(
                    role="tool",
                    parts=tool_response_parts
                ))
                
        err_txt = "Error: Max turns exceeded."
        return {"text": err_txt, "logs": logs} if debug else err_txt
    finally:
        reset_current_user(token)

def skill_call(skill_name, context, 
               documents=None, sys_config=None, 
               conversation_mode: str = 'skill_call', 
               debug=False, on_log=None, 
               purpose: str = None, max_turns=5,  auto_fix_retry: int = 5):
    logs: list[str] = []

    def log(msg: str):
        msg_str = str(msg)
        logs.append(msg_str)
        print(msg_str)
        if callable(on_log):
            try:
                on_log(msg_str)
            except Exception:
                pass

    # 1. 配置 API
    try:
        gem_api_key = APIKey.objects.get(name='Gemini JT').key
    except:
        gem_api_key = getattr(settings, 'GEMINI_API_KEY', '')
    gem_api_key = str(gem_api_key).strip()
    client = genai.Client(api_key=gem_api_key)
    
    # 如果未提供系统提示词，尝试从对话模式默认提示补足
    if not sys_config:
        sys_config = _resolve_mode_prompt(conversation_mode) or sys_config

    if not purpose:
        purpose = _get_purpose_from_mode(conversation_mode) or 'general'

    # 查找指定技能的定义
    # 从 registry 中筛选出目标技能
    target_declaration = None
    for decl in registry.declarations:
        if decl.name == skill_name:
            target_declaration = decl
            break
            
    # 如果没找到动态注册的，尝试找硬编码的
    if not target_declaration:
        # 这里假设 hardcoded tools 也是 FunctionDeclaration 列表
        # (来自 registry.py 的 tools 变量结构比较复杂，这里简化处理)
        # 如果找不到，就抛错或者降级
        err_msg = f"Error: Skill '{skill_name}' not found."
        log(err_msg)
        return {"text": err_msg, "logs": logs} if debug else err_msg

    # 构造仅包含该技能的工具箱
    specific_tool = types.Tool(function_declarations=[target_declaration])
    
    # 构造内容列表
    content_parts = [types.Part(text=context)]
    
    # 2. 处理文档上传
    if documents:
        try:
            for doc in documents:
                # 检查物理文件是否存在
                if os.path.exists(doc.file.path):
                    log(f"Uploading file for skill call: {doc.file.path}")
                    sample_file = client.files.upload(file=doc.file.path)
                    content_parts.append(types.Part.from_uri(
                        file_uri=sample_file.uri,
                        mime_type=sample_file.mime_type
                    ))
                else:
                    log(f"警告：文件不存在 {doc.file.path}")
        except Exception as e:
            log(f"Warning: File upload failed: {e}")

    # 3. 调用 API 生成 (手动处理工具调用以支持重试和修复)
    # 我们先禁用自动调用，获取工具调用请求，手动执行并处理错误
    
    response = None
    excluded_models = []
    
    # 尝试最多 3 次模型回退 (初始请求)
    for model_attempt in range(3):
        try:
            # 动态选择模型
            rec_model = get_recommended_model_name(purpose=purpose, excluded_models=excluded_models, api_key=gem_api_key)
            log(f"Skill Call Init using: {rec_model} (Attempt {model_attempt+1})")

            # 初始请求
            response = client.models.generate_content(
                model=rec_model,   
                config=types.GenerateContentConfig(
                    system_instruction=sys_config,
                    tools=[specific_tool], 
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode="ANY", # 强制模型必须调用工具
                            allowed_function_names=[skill_name]
                        )
                    ),
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    )
                ),
                contents=content_parts,
            )
            break
        except Exception as e:
                err_str = str(e)
                if '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str:
                    log(f"⚠️ Model {rec_model} quota exhausted. Switching model...")
                    excluded_models.append(rec_model)
                    import time
                    time.sleep(2)
                else: 
                     err_msg = f"Error initiating skill call: {str(e)}"
                     return {"text": err_msg, "logs": logs} if debug else err_msg
    
    if not response:
        err_msg = f"Error: Failed to initiate skill call after retries."
        return {"text": err_msg, "logs": logs} if debug else err_msg

    # 检查是否有工具调用
    if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
         err_msg = "Error: Empty response from model during skill init."
         return {"text": err_msg, "logs": logs} if debug else err_msg

    first_content = response.candidates[0].content
    tool_call_part = None
    for part in first_content.parts:
        if part.function_call:
            tool_call_part = part
            break
            
    if not tool_call_part:
        err_msg = f"Error: Model did not decide to call {skill_name}. Response: {response.text}"
        return {"text": err_msg, "logs": logs} if debug else err_msg

    # 手动执行逻辑 (带自动修复和日志)
    fc = tool_call_part.function_call
    name = fc.name
    args = fc.args
    
    # 查找函数实现
    func = registry.functions_dict.get(name)
    result = None
    log_args = args if isinstance(args, dict) else {"args": str(args)}
    
    if not func:
        err_msg = f"Error: Function implementation for {name} not found."
        return {"text": err_msg, "logs": logs} if debug else err_msg

    # 执行重试循环
    execution_success = False
    log(f"--- 🚀 Executing skill {name} ---")
    
    for attempt in range(auto_fix_retry + 1):
        try:
            # Reload function if retrying (in case it was fixed)
            if attempt > 0:
                func = registry.functions_dict.get(name)
                if not func:
                    result = "Function disappeared during reload."
                    break

            # Execute
            if isinstance(args, dict):
                 result = func(**args)
            else:
                 result = func()

            # Log Success
            try:
                SkillExecutionLog.objects.create(
                    skill_name=name,
                    arguments=log_args,
                    status="SUCCESS",
                    result_summary=str(result)[:1000]
                )
            except: pass
            
            execution_success = True
            log(f"Skill execution result: {str(result)[:200]}...")
            break
            
        except Exception as e:
            error_msg = str(e)
            log(f"Error executing {name} in skill_call (Attempt {attempt+1}/{auto_fix_retry+1}): {e}")
            
            if attempt < auto_fix_retry:
                # Attempt Fix
                try:
                    from api_services.skills.root_skill_manager import fix_skill_at_runtime
                    log(f"Attempting auto-fix for {name} (Fix attempt {attempt+1})...")
                    fix_msg = fix_skill_at_runtime(name, traceback.format_exc(), args)
                    log(f"Auto-fix output: {fix_msg}")
                    
                    if "Success" in fix_msg:
                        try:
                            SkillExecutionLog.objects.create(
                                skill_name=name,
                                arguments=log_args,
                                status="AUTO-FIXED",
                                error_message=traceback.format_exc(),
                                result_summary=fix_msg
                            )
                        except: pass
                        continue # Retry loop
                    else:
                        # Fix failed
                        try:
                            SkillExecutionLog.objects.create(
                                skill_name=name,
                                arguments=log_args,
                                status="FAILED",
                                error_message=f"{error_msg}\nFix failed: {fix_msg}"
                            )
                        except: pass
                        result = f"Error: {error_msg}\nAuto-fix failed: {fix_msg}"
                        break
                except Exception as fix_err:
                    log(f"Auto-fix system failed: {fix_err}")
                    result = f"Error: {error_msg}\nAuto-fix system error: {fix_err}"
                    break
            else:
                # Retry exhausted
                try:
                    SkillExecutionLog.objects.create(
                        skill_name=name,
                        arguments=log_args,
                        status="FAILED",
                        error_message=traceback.format_exc()
                    )
                except: pass
                result = f"Error after fix attempt: {traceback.format_exc()}"

    # 4. 将执行结果回传给模型以生成最终描述
    # 构造历史: [UserRequest, ToolCall, ToolResponse]
    history = [
        types.Content(role="user", parts=content_parts),
        first_content, # The tool call
        types.Content(role="tool", parts=[
            types.Part.from_function_response(
                name=name,
                response={"result": result}
            )
        ])
    ]
    
    final_response = None
    # 尝试最多 3 次模型回退 (最终总结)
    excluded_models_final = []
    
    for model_attempt in range(3):
        try:
            # 再次动态选择模型，因为上一个可能刚耗尽
            final_model = get_recommended_model_name(purpose=purpose, excluded_models=excluded_models_final, api_key=gem_api_key)
            log(f"Skill Call Final using: {final_model} (Attempt {model_attempt+1})")
            
            final_response = client.models.generate_content(
                model=final_model, 
                contents=history,
                config=types.GenerateContentConfig(
                    tools=[specific_tool] # Keep tools available just in case
                )
            )
            break
        except Exception as e:
            err_str = str(e)
            if '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str:
                log(f"⚠️ Model {final_model} quota exhausted during final step. Switching...")
                excluded_models_final.append(final_model)
                import time
                time.sleep(2)
            else:
                err_msg = f"Error generating final response: {str(e)}\nInput Result was: {result}"
                return {"text": err_msg, "logs": logs} if debug else err_msg
    
    if final_response:
        return {"text": final_response.text, "logs": logs} if debug else final_response.text
    
    err_msg = f"Error: Failed to generate final response after retries.\nInput Result was: {result}"
    return {"text": err_msg, "logs": logs} if debug else err_msg

def get_content(context, documents=None, 
                sys_config=None, 
                system_prompt_id=None, 
                system_prompt_name=None, 
                conversation_mode: str = 'get_content', 
                purpose: str = None):
    """
    Generate content with optional system prompt selection.
        Input parameters:
        - context: The main text input for content generation
        - documents: Optional list of document objects to upload and include as context
        - sys_config: Explicit system instruction text (highest priority)
        - system_prompt_id: ID of the system prompt to use
        - system_prompt_name: Name of the system prompt to use
        - conversation_mode: Mode of the conversation, affects default system prompt
        - purpose: Purpose of the content generation
    """

    def _resolve_system_instruction():
        sections = []
        if sys_config:
            sections.append(str(sys_config).strip())

        prompt_obj = None
        # 优先使用显式传入的系统提示
        try:
            qs = SystemPrompt.objects.filter(is_active=True)
            if system_prompt_id:
                prompt_obj = qs.get(pk=system_prompt_id)
            elif system_prompt_name:
                prompt_obj = qs.get(role_name=system_prompt_name)
            elif not sys_config:
                # 如果没有显式 sys_config，优先使用 ConversationMode 的默认提示词
                mode_prompt = _resolve_mode_prompt(conversation_mode)
                if mode_prompt:
                    sections.append(mode_prompt)
                else:
                    prompt_obj = qs.filter(is_default=True).first()
        except SystemPrompt.DoesNotExist:
            prompt_obj = None
        except Exception as resolve_err:
            print(f"SystemPrompt resolve error: {resolve_err}")
            prompt_obj = None

        if prompt_obj:
            prompt_lines = [
                f"角色：{prompt_obj.role_name}",
                f"角色定义：{prompt_obj.role_definition}",
                f"提示词：{prompt_obj.prompt_content}",
            ]
            sections.append("\n".join(prompt_lines))

        merged = [part for part in sections if str(part).strip()]
        return "\n\n".join(merged) if merged else None

    # 1. 配置 API
    try:
        gem_api_key = APIKey.objects.get(name='Gemini Auto Process').key
    except:
        gem_api_key = getattr(settings, 'GEMINI_API_KEY', '')
    gem_api_key = str(gem_api_key).strip()
    client = genai.Client(api_key=gem_api_key)
    
    # 构造内容列表
    content_parts = [context]
    final_sys_config = _resolve_system_instruction()
    
    if not purpose:
        purpose = _get_purpose_from_mode(conversation_mode) or 'general'
                
    try:
        # 3. 处理文档上传
        if documents:
            import mimetypes
            file_names = []
            for doc in documents:
                # 检查物理文件是否存在
                if os.path.exists(doc.file.path):
                    try:
                        file_path = doc.file.path
                        file_name = os.path.basename(file_path)
                        # 获取文件 MIME 类型
                        mime_type, _ = mimetypes.guess_type(file_path)
                        
                        # 规避 Unicode 文件名导致的 Header 编码错误
                        # 使用 ASCII 安全的文件名进行上传
                        # 1. 读取文件内容
                        with open(file_path, 'rb') as f:
                            file_content = f.read()
                        
                        # 2. 构造 BytesIO 对象，这样 SDK 就不会自动读取文件名到 Header
                        import io
                        file_io = io.BytesIO(file_content)
                        file_io.name = file_name.encode('ascii', 'ignore').decode('ascii') or 'unnamed_file'
                        
                        # 3. 手动指定 MIME 类型（因为流对象无法自动猜测）
                        sample_file = client.files.upload(
                            file=file_io,
                            config={'mime_type': mime_type or 'application/octet-stream'}
                        )
                        content_parts.append(sample_file)
                    except Exception as e:
                        print(f"上传文件失败: {e}")
                else:
                    print(f"警告：文件不存在 {doc.file.path}")

        # 3. 调用 API 生成（改为动态模型，且支持 purpose）
        model_name = get_recommended_model_name(purpose=purpose, api_key=gem_api_key)
        response = client.models.generate_content(
            model=model_name,
            config=types.GenerateContentConfig(system_instruction=final_sys_config),
            contents=content_parts,
        )

        # 4. 获取返回结果并确保不为 None
        if response and response.text:
            return response.text
        else:
            print("Gemini 返回了空内容")
            return "⚠️ AI 无法生成有效内容，请检查上下文或文件。"

    except Exception as e:
        # 这里建议打印完整堆栈，方便排查 API 权限或网络问题
        print(f"Gemini API 调用失败: {e}")
        print(traceback.format_exc())
        return None

