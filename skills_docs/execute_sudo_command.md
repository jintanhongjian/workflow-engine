# `execute_sudo_command`

*(Generated on 2026-03-06 12:04:24)*

**Import Path**: `from api_services.skills.root_skill_manager import execute_sudo_command`

使用 sudo 执行任意系统命令。请谨慎使用。

### Parameters

| Parameter | Type | Description | Required |
| :--- | :--- | :--- | :--- |
| `command` | *string* | Shell 命令 | ✅ Yes |
| `password` | *string* | sudo 密码 (可选) | No |