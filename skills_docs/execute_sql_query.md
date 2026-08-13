# `execute_sql_query`

*(Generated on 2026-03-06 12:04:24)*

**Import Path**: `from api_services.skills.db_search import execute_sql_query`

执行只读 SQL 查询并返回结果。注意：仅支持 SELECT 查询，禁止修改数据。

### Parameters

| Parameter | Type | Description | Required |
| :--- | :--- | :--- | :--- |
| `sql_query` | *string* | 要执行的 SQL 查询语句 | ✅ Yes |