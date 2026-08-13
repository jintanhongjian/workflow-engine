# `replace_file_content`

*(Generated on 2026-03-06 12:04:24)*

**Import Path**: `from api_services.skills.file_editor import replace_file_content`

修改和替换指定文件中的文本内容。

### Parameters

| Parameter | Type | Description | Required |
| :--- | :--- | :--- | :--- |
| `file_path` | *string* | 需要修改的文件的绝对路径或相对路径。 | ✅ Yes |
| `old_string` | *string* | 需要被替换的原始字符串（或正则表达式）。 | ✅ Yes |
| `new_string` | *string* | 替换后的新字符串。 | ✅ Yes |
| `use_regex` | *boolean* | 是否将 old_string 作为正则表达式处理，默认为 False。 | No |
| `backup` | *boolean* | 是否在修改前备份原文件（生成 .bak 文件），默认为 True。 | No |