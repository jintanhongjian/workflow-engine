# AI Skills Catalog

*(Generated on 2026-03-06 12:04:24)*

This catalog lists all available skills and their documentation paths. Use these links to find detailed parameters and usage instructions.

- [create_user_task](./create_user_task.md) - Create a UserScheduledTask for the current user using provided parameters.
- [get_memory_usage](./get_memory_usage.md) - Returns the current system's memory usage statistics.
- [replace_file_content](./replace_file_content.md) - 修改和替换指定文件中的文本内容。
- [scrape_and_download_files](./scrape_and_download_files.md) - Scrape main text and download specific types of files from a list of URLs.
- [generate_image_with_gemini_nano_banana](./generate_image_with_gemini_nano_banana.md) - 使用 Gemini Nano Banana (Imagen 4) 生成图片。
- [simple_translate](./simple_translate.md) - Safely translates text to the target language.
- [send_email_skill](./send_email_skill.md) - 发送邮件；支持纯文本、HTML 或 Markdown 正文.
- [execute_sql_query](./execute_sql_query.md) - 执行只读 SQL 查询并返回结果。注意：仅支持 SELECT 查询，禁止修改数据。
- [get_table_schema](./get_table_schema.md) - 获取指定数据表的结构信息（DDL 或 字段描述）。
- [list_all_tables](./list_all_tables.md) - 列出数据库中所有可用的数据表名称。
- [create_and_register_skill](./create_and_register_skill.md) - 根据自然语言描述自动生成、验证并在系统中注册（用@register_skill装饰器）一个新的 Python 技能。
- [execute_sudo_command](./execute_sudo_command.md) - 使用 sudo 执行任意系统命令。请谨慎使用。
- [fix_skill_at_runtime](./fix_skill_at_runtime.md) - Attempts to fix a skill that failed at runtime using AI.
- [generate_skill_documentation](./generate_skill_documentation.md) - 生成所有已注册技能的 Markdown 文档，每个技能生成一个单独的文件，文件名为技能函数名。