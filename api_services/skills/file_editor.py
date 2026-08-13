import os
import re
from typing import Optional
from .decorators import register_skill

@register_skill
def replace_file_content(file_path: str, old_string: str, new_string: str, use_regex: bool = False, backup: bool = True) -> str:
    """
    修改和替换指定文件中的文本内容。
    
    :param file_path: 需要修改的文件的绝对路径或相对路径。
    :param old_string: 需要被替换的原始字符串（或正则表达式）。
    :param new_string: 替换后的新字符串。
    :param use_regex: 是否将 old_string 作为正则表达式处理，默认为 False。
    :param backup: 是否在修改前备份原文件（生成 .bak 文件），默认为 True。
    :return: 执行结果说明。
    """
    if not os.path.exists(file_path):
        return f"错误：找不到文件 - {file_path}"
    
    if not os.path.isfile(file_path):
        return f"错误：指定的路径不是一个文件 - {file_path}"

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if backup:
            backup_path = f"{file_path}.bak"
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(content)

        if use_regex:
            new_content, count = re.subn(old_string, new_string, content)
            if count == 0:
                return f"提示：在文件中未找到匹配正则表达式的内容 {old_string}，未作任何修改。"
        else:
            if old_string not in content:
                return f"提示：在文件中未找到指定的原始内容，未作任何修改。"
            new_content = content.replace(old_string, new_string)
            count = content.count(old_string)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return f"成功：共替换了 {count} 处内容。文件已更新：{file_path}"

    except Exception as e:
        return f"错误：处理文件或替换文件内容时发生异常: {str(e)}"
