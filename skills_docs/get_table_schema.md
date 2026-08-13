# `get_table_schema`

*(Generated on 2026-03-06 12:04:24)*

**Import Path**: `from api_services.skills.db_search import get_table_schema`

获取指定数据表的结构信息（DDL 或 字段描述）。

### Parameters

| Parameter | Type | Description | Required |
| :--- | :--- | :--- | :--- |
| `table_names` | *string* | 表名，支持多个表名用逗号分隔，例如 "auth_user, api_services_userprofile" | ✅ Yes |