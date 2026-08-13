# `generate_skill_documentation`

*(Generated on 2026-03-06 12:04:24)*

**Import Path**: `from api_services.skills.root_skill_manager import generate_skill_documentation`

生成所有已注册技能的 Markdown 文档，每个技能生成一个单独的文件，文件名为技能函数名。

### Parameters

| Parameter | Type | Description | Required |
| :--- | :--- | :--- | :--- |
| `output_dir` | *string* | 文档输出目录，默认为项目根目录下的 skills_docs | No |