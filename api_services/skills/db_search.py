
import json
import sqlite3
from django.db import connection
from .decorators import register_skill

@register_skill
def list_all_tables() -> str:
    """
    列出数据库中所有可用的数据表名称。
    
    :return: 一个包含所有表名的 JSON 格式列表字符串
    """
    try:
        with connection.cursor() as cursor:
            # 兼容不同数据库后端，这里优先考虑 SQLite
            # 对于 SQLite: select name from sqlite_master where type='table';
            # 对于 PostgreSQL: SELECT table_name FROM information_schema.tables WHERE table_schema='public';
            
            if connection.vendor == 'sqlite':
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'django_migrations';")
            else:
                # 默认尝试标准 SQL 或 Django introspection (这里简化处理)
                return "当前仅支持 SQLite 数据库的表列表查询。"
                
            tables = [row[0] for row in cursor.fetchall()]
        return json.dumps(tables, ensure_ascii=False)
    except Exception as e:
        return f"Error listing tables: {str(e)}"

@register_skill
def get_table_schema(table_names: str) -> str:
    """
    获取指定数据表的结构信息（DDL 或 字段描述）。
    
    :param table_names: 表名，支持多个表名用逗号分隔，例如 "auth_user, api_services_userprofile"
    :return: 包含表结构的文本描述
    """
    if not table_names:
        return "请提供表名。"
    
    tables = [t.strip() for t in table_names.split(',')]
    schemas = []
    
    try:
        if connection.vendor == 'sqlite':
            with connection.cursor() as cursor:
                for table in tables:
                    # 获取 Create Statement
                    cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name=?", [table])
                    row = cursor.fetchone()
                    if row:
                        schemas.append(f"Table: {table}\n{row[0]};\n")
                    else:
                        schemas.append(f"Table {table} not found.")
        else:
            return "当前仅支持 SQLite 数据库的表结构查询。"
            
        return "\n".join(schemas)
    except Exception as e:
        return f"Error getting schema: {str(e)}"

@register_skill
def execute_sql_query(sql_query: str) -> str:
    """
    执行只读 SQL 查询并返回结果。注意：仅支持 SELECT 查询，禁止修改数据。
    
    :param sql_query: 要执行的 SQL 查询语句
    :return: 查询结果（JSON 格式）或 错误信息
    """
    sql_lower = sql_query.strip().lower()
    if not sql_lower.startswith('select') and not sql_lower.startswith('with') and not sql_lower.startswith('explain'):
        return "Error: 仅允许执行 SELECT 查询 (Read-only)."
        
    forbidden_keywords = ['drop', 'delete', 'update', 'insert', 'alter', 'truncate', 'grant', 'revoke']
    if any(keyword in sql_lower for keyword in forbidden_keywords):
         # 简单的关键词检查，防止显而易见的破坏性操作
         # 注意：这不是完美的防御，生产环境应使用只读数据库用户
         return f"Error: SQL 中包含禁止的关键词，仅允许只读操作。"

    try:
        with connection.cursor() as cursor:
            cursor.execute(sql_query)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            
            # 将结果转换为列表字典
            results = []
            for row in rows:
                # 处理可能无法序列化的类型（如 datetime）
                row_dict = {}
                for idx, value in enumerate(row):
                    if hasattr(value, 'isoformat'):
                        row_dict[columns[idx]] = value.isoformat()
                    else:
                        row_dict[columns[idx]] = value
                results.append(row_dict)
                
            # 限制返回行数以防 Token 溢出
            if len(results) > 100:
                results = results[:100]
                results.append({"_warning": "Result truncated to 100 rows."})
                
            return json.dumps(results, ensure_ascii=False, indent=2)
            
    except Exception as e:
        return f"SQL Error: {str(e)}"

