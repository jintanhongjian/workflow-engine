
import os
import sys
import django
import json
from django.conf import settings
from google import genai
from google.genai import types

DJANGO_READY = False


def _try_setup_django() -> bool:
    global DJANGO_READY
    if DJANGO_READY:
        return True

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    candidates = ['workflow-engine.settings', 'workflow_engine.settings']
    last_error = None

    for module_name in candidates:
        try:
            os.environ.setdefault('DJANGO_SETTINGS_MODULE', module_name)
            django.setup()
            DJANGO_READY = True
            return True
        except Exception as e:
            last_error = e
            # reset before trying next candidate
            DJANGO_READY = False
            continue

    print(f"Warning: Django setup failed, fallback to env key only. error={last_error}")
    return False


def _get_gemini_api_key() -> str | None:
    if _try_setup_django():
        try:
            from api_services.models import APIKey
            key_obj = APIKey.objects.filter(name='Gemini JT', is_active=True).first() or APIKey.objects.filter(name='Gemini JT').first()
            if key_obj and key_obj.key:
                return key_obj.key.strip()
        except Exception:
            pass

        try:
            key_from_settings = str(getattr(settings, 'GEMINI_API_KEY', '')).strip()
            if key_from_settings:
                return key_from_settings
        except Exception:
            pass

    key_from_env = os.getenv('GEMINI_API_KEY', '').strip()
    return key_from_env or None


def _obj_to_dict(obj):
    if obj is None:
        return {}
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    if isinstance(obj, dict):
        return obj
    try:
        return dict(obj)
    except Exception:
        return {}


def _extract_model_limits(model_obj):
    data = _obj_to_dict(model_obj)
    if not data:
        data = {k: getattr(model_obj, k, None) for k in dir(model_obj) if not k.startswith('_')}

    keys = [
        'input_token_limit',
        'output_token_limit',
        'context_window',
        'max_output_tokens',
        'supported_actions',
        'supported_generation_methods',
    ]
    return {k: data.get(k) for k in keys if data.get(k) is not None}


def _extract_quota_info_from_error(err):
    text = str(err)
    info = {
        'ok': False,
        'status': 'ERROR',
        'message': text,
        'retry_delay': None,
        'quota_violations': [],
    }

    # 尝试提取 retryDelay
    retry_match = None
    try:
        import re
        retry_match = re.search(r"'retryDelay':\s*'([^']+)'", text)
    except Exception:
        pass
    if retry_match:
        info['retry_delay'] = retry_match.group(1)

    # 尝试提取 quotaMetric / quotaId
    try:
        import re
        violations = re.findall(r"'quotaMetric':\s*'([^']+)'.*?'quotaId':\s*'([^']+)'", text, re.DOTALL)
        for metric, quota_id in violations:
            info['quota_violations'].append({'quotaMetric': metric, 'quotaId': quota_id})
    except Exception:
        pass

    if '429' in text or 'RESOURCE_EXHAUSTED' in text:
        info['status'] = 'QUOTA_EXHAUSTED'
    return info


def _probe_model_quota(client, model_name: str):
    """
    轻量探测模型可用性。
    说明：Gemini API 暂无“剩余额度”官方字段，这里通过一次最小请求判断当前是否可调用。
    """
    try:
        client.models.generate_content(
            model=model_name,
            contents='ping',
            config=types.GenerateContentConfig(max_output_tokens=1),
        )
        return {
            'ok': True,
            'status': 'AVAILABLE',
            'message': 'Probe request succeeded',
            'retry_delay': None,
            'quota_violations': [],
        }
    except Exception as e:
        return _extract_quota_info_from_error(e)


def auto_select_model(model_results: list[dict], purpose: str = 'general', excluded_models: list[str] = None, return_all: bool = False) -> dict | list[dict] | None:
    """
    根据模型探测结果动态推荐模型。

    purpose:
      - general: 通用文本生成
      - coding: 代码生成/修复
      - fast: 优先低延迟
    excluded_models:
      - 要排除的模型名称列表（例如刚刚发生配额错误的模型）
    return_all:
      - 如果为 True，则返回排序后的所有候选模型列表。
    """
    if not model_results:
        return None
    
    excluded_models = excluded_models or []
    # Normalize excluded names to ensure matching
    normalized_excluded = [m.replace('models/', '') for m in excluded_models]

    candidates = []
    import re

    for item in model_results:
        model_name = item.get('model')
        limits = item.get('limits', {}) or {}
        # 注意: item['quota_probe'] 可能是 None (如果 SKIPPED), 或者是 dict
        probe = item.get('quota_probe') or {}

        if not model_name or not isinstance(model_name, str):
            continue
        
        # Check exclusion
        simple_model_name = model_name.replace('models/', '')
        if simple_model_name in normalized_excluded:
             continue
             
        if 'gemini' not in model_name.lower():
            continue
            
        # 允许 SKIPPED 状态或成功的模型
        is_ok = probe.get('ok') is True
        is_skipped = probe.get('status') == 'SKIPPED'
        
        if not is_ok and not is_skipped:
            continue

        actions = limits.get('supported_actions') or []
        if actions and 'generateContent' not in actions:
            continue

        input_limit = limits.get('input_token_limit') or 0
        output_limit = limits.get('output_token_limit') or 0

        # 基础分：可用模型才会进入；版本与能力驱动排序
        score = 100

        # 按模型版本优先，数值越高优先级越高
        version_match = re.search(r'gemini-(\d+\.\d+)', model_name)
        if version_match:
            version_val = float(version_match.group(1))
            score += version_val * 1000  # 2.0 -> 2000, 1.5 -> 1500

        # 细粒度加分：高阶/推理/快速
        lower_name = model_name.lower()
        if 'pro' in lower_name:
            score += 50
        if 'thinking' in lower_name:
            score += 60
        if 'flash' in lower_name:
            score += 20
        if 'exp' in lower_name:
            score += 5

        # 按 token 上限微调
        score += min(int(input_limit / 50000), 40)
        score += min(int(output_limit / 2000), 20)

        candidates.append({
            'model': model_name,
            'score': score,
            'input_token_limit': input_limit,
            'output_token_limit': output_limit,
            'supported_actions': actions,
            'purpose': purpose,
            'quota_probe': probe, # Keep probe info
        })

    if not candidates:
        return None

    # 按分数降序排列
    candidates.sort(key=lambda x: x['score'], reverse=True)
    
    if return_all:
        return candidates
        
    return candidates[0]


def get_recommended_model_name(purpose: str = 'coding', excluded_models: list[str] = None, api_key: str = None) -> str:
    """
    直接获取推荐的模型名称字符串。如果获取失败，返回默认值。
    支持排除列表，用于失败重试。
    """
    try:
        gem_api_key = api_key or _get_gemini_api_key()
        
        # 1. 快速获取所有模型列表（跳过探测），以减少初始延迟
        results = list_gemini_models(purpose=purpose, verbose=False, api_key=gem_api_key, skip_probe=True) 
        
        # 2. 对候选模型进行排序（按版本高低）
        candidates = auto_select_model(results, purpose=purpose, excluded_models=excluded_models, return_all=True)
        
        if not candidates:
             # 如果没有候选，尝试回退默认
             pass 
        else:
             client = genai.Client(api_key=gem_api_key)
             # 3. 按优先级逐个探测，直到找到一个可用的
             for cand in candidates:
                 model_name = cand['model']
                 probe_info = cand.get('quota_probe', {})
                 
                 # 如果是 SKIPPED，则需要现场探测
                 if probe_info.get('status') == 'SKIPPED':
                     probe_res = _probe_model_quota(client, model_name)
                     if not probe_res.get('ok'):
                         # 探测失败，尝试下一个
                         continue
                 elif not probe_info.get('ok'):
                     # 已知不可用
                     continue
                 
                 # 找到可用模型
                 if model_name.startswith('models/'):
                     return model_name.split('/', 1)[1]
                 return model_name
                 
    except Exception as e:
        print(f"Warning: Failed to auto-select model: {e}")
    
    # Fallback default
    # If default is also excluded, try another fallback
    default_model = 'gemini-2.0-flash'
    std_default = 'gemini-1.5-flash'
    
    exclusion_set = set(excluded_models or [])
    exclusion_set.update({m.replace('models/', '') for m in exclusion_set})

    if default_model in exclusion_set or f"models/{default_model}" in exclusion_set:
         return std_default  # Ultimate fallback
    return default_model


def list_gemini_models(purpose: str = 'coding', verbose: bool = True, api_key: str = None, skip_probe: bool = False):
    gem_api_key = api_key or _get_gemini_api_key()
    if not gem_api_key:
        if verbose:
             print("Error: Gemini API key not found. Please configure APIKey(name='Gemini JT') or GEMINI_API_KEY env.")
        return []

    client = genai.Client(api_key=gem_api_key)
    try:
        models = client.models.list()
        model_list = list(models)
        if verbose:
            print(f"Found models: {len(model_list)}")

        results = []
        for m in model_list:
            model_name = getattr(m, 'name', None) or _obj_to_dict(m).get('name', 'unknown')
            # 提取限制
            # 注意: _extract_model_limits 需要保证在当前作用域可用，假设它在文件前面定义了
            try:
                limits = _extract_model_limits(m)
            except:
                limits = {}

            # 仅对 gemini 系列做可用性探测，避免对图片/嵌入等模型发送无效请求
            do_probe = isinstance(model_name, str) and 'gemini' in model_name.lower()
            
            probe = {
                    'ok': None,
                    'status': 'SKIPPED', 
                    'message': 'Quota probe skipped',
                    'retry_delay': None,
                    'quota_violations': [],
                }

            if do_probe and not skip_probe:
                 probe = _probe_model_quota(client, model_name)

            results.append({
                'model': model_name,
                'limits': limits,
                'quota_probe': probe,
            })


        if verbose:
            recommendation = auto_select_model(results, purpose=purpose)
            output = {
                'purpose': purpose,
                'recommended_model': recommendation,
                'models': results,
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
            
        return results
    except Exception as e:
        if verbose:
            print(f"Error inspecting models: {e}")
        return []


if __name__ == "__main__":
    # 可通过环境变量 MODEL_SELECT_PURPOSE 控制推荐策略: general/coding/fast
    list_gemini_models(purpose=os.getenv('MODEL_SELECT_PURPOSE', 'coding'), verbose=True)
