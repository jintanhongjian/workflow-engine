# `create_and_register_skill`

*(Generated on 2026-03-06 12:04:24)*

**Import Path**: `from api_services.skills.root_skill_manager import create_and_register_skill`

根据自然语言描述自动生成、验证并在系统中注册（用@register_skill装饰器）一个新的 Python 技能。

### Parameters

| Parameter | Type | Description | Required |
| :--- | :--- | :--- | :--- |
| `description` | *string* | 技能的详细功能描述。AI 将根据此描述推断文件名、安装依赖、生成代码和测试用例。 | ✅ Yes |
| `max_retries` | *integer* | 最大尝试修复代码的次数。 | No |