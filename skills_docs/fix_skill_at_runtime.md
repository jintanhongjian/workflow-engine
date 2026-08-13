# `fix_skill_at_runtime`

*(Generated on 2026-03-06 12:04:24)*

**Import Path**: `from api_services.skills.root_skill_manager import fix_skill_at_runtime`

Attempts to fix a skill that failed at runtime using AI.

### Parameters

| Parameter | Type | Description | Required |
| :--- | :--- | :--- | :--- |
| `skill_name` | *string* | The name of the function that failed. | ✅ Yes |
| `error_trace` | *string* | The traceback string of the exception. | ✅ Yes |
| `args` | *string* | The arguments passed to the function when it failed. | No |