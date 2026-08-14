# Workflow Engine 

这是一个基于 Django、Celery 和 Redis 构建的自动化工作流系统，致力于实现 AI 服务对接（Google Gemini, OpenAI）、企微通知、RPA 支持任务调度管理的综合引擎平台。

## 系统架构与技术栈

* **Web 框架**: Django 6.0+
* **前端展示**: Tailwind CSS (通过 Node.js 包环境管理)
* **任务队列**: Celery 5.4+ (与 Django 紧密集成)
* **消息队列中间件**: Redis
* **生产服务器**: Gunicorn (运行 WSGI 应用)
* **依赖管理**: `uv` (新一代 Python 包构建与管理工具)
* **API 与 SDK 支持**: Google Gemini、OpenAI、WeCom (企业微信)、n8n 等。

## 环境要求

* Linux 服务器环境（推荐 Ubuntu/Debian）
* Python 3.12
* Node.js 20+
* PostgreSQL 环境 (可选，支持配置业务数据库)
* 本地 SQLite (Django 默认库，以及 Celery-beat 配置)
* Redis

## 快速安装与部署

本项目提供自动化的一键安装脚本，可自动检查包管理器、安装系统依赖、Node/Redis、虚拟环境与 Python 包依赖，并进行数据库初始化工作。

1. **进入项目目录**并赋予脚本执行权限：
   ```bash
   cd /home/joehong/workflow-engine
   chmod +x *.sh
   ```

2. **执行自动部署脚本**：
   ```bash
   ./install.sh
   ```
   > 脚本将自动安装 `uv` 等工具，创建 `.venv` 虚拟环境，并安装 `requirements.txt`。同时会帮助你在 `~/.workflow_engine_env` 预写入环境变量配置。

3. **配置API密钥** (非常重要)：
   系统运行依赖 API Key 权限。为了安全，这些信息应配置为系统的环境变量。你可以在启动前或者在 `.bashrc`、`~/.profile` 中补充（也可以写到 `~/.workflow_engine_env` 文件里由系统自己 source 引用）：
   ```bash
   export GEMINI_API_KEY="your-gemini-api-key"
   export GITHUB_API_KEY="your-github-api-key"
   export TKH_N8N_API_KEY="your-tkh-n8n-api-key"
   ```

## 服务管理 (启停与监控)

本项目包含了完整的服务管理统筹脚本 `service_control.sh`，可一键管理包含 Web 服务器 (Gunicorn) 和 任务队列 (Celery Worker & Celery Beat) 以及 Redis 服务。

### 常用命令
（在执行前，请确保你在虚拟环境中 `source .venv/bin/activate` 或由脚本内部分配应用账号权限完成分发启动）

* **一键启全线服务 (Gunicorn, Celery Worker, Celery Beat, Redis)**：
  ```bash
  ./service_control.sh start
  ```
* **一键停止所有服务**：
  ```bash
  ./service_control.sh stop
  ```
* **查看各服务状态**：
  ```bash
  ./service_control.sh status
  ```
* **重启所有服务**：
  ```bash
  ./service_control.sh restart
  ```

### 服务监控与进程自愈
你可以利用 `monitor_services.sh` 作为守护进程，保障因系统意外宕机的组件重新拉端启动：
```bash
./monitor_services.sh --interval 60 
```

## 目录结构说明

* **`api_services/`**: 系统核心 API 服务，提供对外能力及系统内技能服务逻辑及技能页面 (Skills) 支持。
* **`ai_subscription/`**: AI 订阅应用能力组件模块。
* **`approve_flow/`**: 系统内置审批流定义、视图处理逻辑模块。
* **`workflow-engine/`**: Django 项目系统核心设置与总路由定义（主 `settings.py` 所在处）。
* **`logs/`**: 相关服务器（Gunicorn）和定时任务节点调度队列产生的日志统一汇聚地。
* **`pids/`**: 服务进程 PID 持久化定位，供守护和启停分析使用。

---

## 附录：UserScheduledTask 定时任务附件自动注入指引

系统后台支持在 `UserScheduledTask` 模块新建具有附件依赖的定期调度任务，自动把通过 `TaskAttachment` 控件上传的物理文件在运行时注给开发函数的传入对象中。

### 1) 参数名智能映射配置 
在 `workflow-engine/settings.py` 中有如下预设映射判断：
```python
TASK_ATTACHMENT_PARAM_NAMES = ['attachments', 'attachment', 'files', 'file_paths', 'docs', 'documents']
TASK_ATTACHMENT_PARAM_KEYWORDS = ['attachment', 'file', 'doc']
```
* **原理**: 当绑定的任务函数参数名命中上述任意规则时，调度执行时系统会把当前任务在平台面上传所绑定的文件路径替代送入。若参数类别为 `list`，注入全部路径数组，若非数组型列表，仅注入该层级里第一个有效文件路径。

### 2) Admin 后台实操步骤
1. 进入 Django Admin 后台，操作新建或者修改 `UserScheduledTask` 任务。
2. 下拉框选择将要在 Celery 执行的 `task_name`（比如选择某一个用于文本解析处理和发件逻辑的函数），这时候后台会动态展示对应函数该需要的参数形态（`task_params`）。
3. 界面靠下存在附件上传控制区 `TaskAttachment`，上传所需要分析文件。
4. 点击保存后，系统的表间信号等机制将会检查 `kwargs`，把这些有效文件的路径准确替换。

### 3) 典型排错问题 (FAQ)

* **Q: 为什么刚才写的 `task_params` 在切 `task_name` 时被刷白了？**
  * **A:** 此为目前前端页的保护机制：在切换新函数时弹框提醒如果决定采用，默认新发重取函数默认参数原型避免类型数据污染所引发任务挂掉，如果想坚持目前表单输入的话在切换提醒点**取消**即可。
* **Q: 文件传完了但系统没把内容注入给目标变量里**
  * **A:** 第一请确定目标函数声明在 `settings.py` 提供匹配名称上；第二再去检查模型面板本身附件是成功绑定且被实际存在盘体物理目录中。
* **Q: 发生系统更新版本时的注意点？**
  * **A:** 涉及含有数据库修改结构变更的情况下（例如增加字段或模型补全文件自动命名类回填操作等如历史记录产生的`0015,0016`版本升级时），千万注意在拉取合并代码后再次执行 `uv run manage.py migrate api_services` 让其彻底跑进 SQLite 业务端去，同时手动验证 `UserScheduledTask.last_run_at` 获取确保整体工作机能依旧完好生效。

