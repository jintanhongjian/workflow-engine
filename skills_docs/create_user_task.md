# `create_user_task`

*(Generated on 2026-03-06 12:04:24)*

**Import Path**: `from api_services.skills.task_creator import create_user_task`

Create a UserScheduledTask for the current user using provided parameters.

### Parameters

| Parameter | Type | Description | Required |
| :--- | :--- | :--- | :--- |
| `title` | *string* | Parameter title | ✅ Yes |
| `description` | *string* | Parameter description | No |
| `task_name` | *string* | Parameter task_name | No |
| `task_params` | *string* | Parameter task_params | No |
| `plan_type` | *string* | Parameter plan_type | No |
| `interval` | *integer* | Parameter interval | No |
| `interval_period` | *string* | Parameter interval_period | No |
| `period_type` | *string* | Parameter period_type | No |
| `spec_date` | *string* | Parameter spec_date | No |
| `is_recurring` | *boolean* | Parameter is_recurring | No |
| `is_active` | *boolean* | Parameter is_active | No |
| `user_id` | *string* | Parameter user_id | No |