## UserScheduledTask 附件参数自动映射

系统会在保存定时任务时，自动将 `TaskAttachment` 上传的附件路径注入到任务参数中。

可在 `workflow-engine/settings.py` 中配置以下两个变量：

- `TASK_ATTACHMENT_PARAM_NAMES`：精确参数名匹配（优先级最高）
- `TASK_ATTACHMENT_PARAM_KEYWORDS`：关键字模糊匹配（兜底）

默认配置示例：

```python
TASK_ATTACHMENT_PARAM_NAMES = [
	'attachments',
	'attachment',
	'files',
	'file_paths',
	'docs',
	'documents',
]

TASK_ATTACHMENT_PARAM_KEYWORDS = [
	'attachment',
	'file',
	'doc',
]
```

说明：

- 当任务函数参数名命中上述规则时，会自动使用该任务关联的 `TaskAttachment` 文件路径。
- 若参数类型为 `list`，会注入全部附件路径；否则注入首个附件路径（无附件则为 `None`）。

## 后台使用步骤（Admin）

1. 进入 `UserScheduledTask` 新建或编辑任务。
2. 选择 `task_name`，系统会展示该任务函数参数说明，并可初始化 `task_params` 模板。
3. 在同页的附件区域上传一个或多个 `TaskAttachment`。
4. 保存任务后，系统会自动将附件路径注入命中的任务参数字段（如 `attachments`、`files` 等）。

### 验证方式

- 在 Django Admin 中查看该任务关联的 `PeriodicTask.kwargs`，确认附件参数已被替换为上传文件路径。
- 如果未注入，请检查任务函数参数名是否命中 `TASK_ATTACHMENT_PARAM_NAMES` 或 `TASK_ATTACHMENT_PARAM_KEYWORDS`。

## 常见问题（FAQ）

### 1) 为什么切换 `task_name` 后，`task_params` 被覆盖？

- 这是当前后台设计：切换任务函数时会弹出确认框，确认后用新任务的参数模板覆盖 `task_params`，避免旧任务参数污染新任务。

### 2) 我不想覆盖已有 `task_params`，怎么办？

- 在切换任务时选择“取消”。
- 如需改为“仅空值时填充、不强制覆盖”，可调整 `api_services/static/api_services/js/user_scheduled_task_admin.js` 的切换逻辑。

### 3) 附件已上传，但任务参数里没有附件路径？

- 先确认任务函数参数名能命中映射规则（`TASK_ATTACHMENT_PARAM_NAMES` / `TASK_ATTACHMENT_PARAM_KEYWORDS`）。
- 再确认附件是挂在当前 `UserScheduledTask` 下，并已成功保存。
- 最后检查 `PeriodicTask.kwargs` 中对应参数是否被注入。

### 4) 为什么有两个附件文件名相关迁移（`0015`、`0016`）？

- `0015` 是历史变更，字段默认值存在不规范情况。
- `0016` 是后续修正，将 `TaskAttachment.filename` 统一为 `blank=True, default=''`，并配合模型 `save()` 自动回填上传文件名。
- 线上环境以最新迁移状态为准，执行 `migrate` 后即可保持一致行为。

## 升级检查清单（发布前）

- 执行迁移：`uv run manage.py migrate api_services`
- 健康检查：`uv run manage.py check`
- 后台新增 `UserScheduledTask` 并上传附件，确认 `TaskAttachment.filename` 自动回填为上传文件名
- 任务保存后检查 `PeriodicTask.kwargs`，确认附件参数（如 `attachments/files/docs`）已注入文件路径
- 手动触发一次任务，确认 `UserScheduledTask.last_run_at` 有更新
