# MiniClaudeCode

一个精简的 Claude Code 风格 AI 编程助手，使用 Anthropic-compatible API（默认 DeepSeek）。

## 快速开始

```bash
# 1. 配置 API Key
cp .env.example .env
# 编辑 .env，填入你的 API Key 和模型

# 2. 安装依赖
pip install anthropic python-dotenv

# 3. 启动
python main.py
```

## 架构

```
main.py              # 入口层：CLI、client 初始化、hook 系统、依赖组装
agent_loop.py        # 执行引擎：主循环、重试恢复、tool 结果收集
tooling.py           # 工具基础设施：ToolRegistry、ToolContext、ToolResult
tools/               # 内置工具集
permissions.py       # 权限系统：deny list、destructive 检测、用户 prompt
context_compactor.py # 上下文压缩：结构化摘要保留
context_cybernetics.py # 上下文控制论：自适应压缩编排
background_tasks.py  # 后台任务管理
skills.py            # 技能系统
```

### 核心模块

| 模块 | 职责 |
|------|------|
| `main.py` | CLI 入口、Anthropic client 初始化、hook 注册、工具注册表组装、依赖注入 |
| `agent_loop.py` | Agent 主循环、API 调用与重试恢复、后台任务调度、todo 提醒注入 |
| `tooling.py` | `ToolRegistry` 执行器、`ToolContext`（cwd/state/runtime）、`ToolResult` |
| `permissions.py` | `PermissionManager`：deny list、destructive pattern、文件路径白名单、逐 turn / 永久放行 |
| `context_compactor.py` | 结构化压缩：保留编号列表、块引、TODO，裁剪按需加载 |
| `context_cybernetics.py` | 多策略压缩编排：snip → micro → reactive → full compact |

### 工具列表

| 工具 | 用途 |
|------|------|
| `bash` | 执行 shell 命令 |
| `read_file` | 读取文件 |
| `write_file` | 写入文件 |
| `edit_file` | 精确字符串替换 |
| `grep_files` | 正则搜索文件内容 |
| `glob_search` | 文件名匹配 |
| `list_files` | 列出目录 |
| `run_command` | 工作区限定的开发命令（无 `shell=True` 注入风险） |
| `patch_file` | 结构化 patch 应用 |
| `todo_write` | 写入待办列表 |
| `task` / `create_task` / `claim_task` / `complete_task` | 任务管理 |
| `schedule_cron` / `cancel_cron` / `list_crons` | 定时任务 |
| `spawn_teammate` / `send_message` / `check_inbox` | 多 agent 协作 |
| `create_worktree` / `remove_worktree` / `keep_worktree` | Git worktree 隔离 |
| `request_plan` / `review_plan` / `request_shutdown` | 子 agent 协议 |
| `compact` | 手动触发上下文压缩 |
| `load_skill` | 加载技能 |

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ANTHROPIC_API_KEY` | API Key | (必填) |
| `ANTHROPIC_BASE_URL` | API 端点 | `https://api.deepseek.com/anthropic` |
| `MODEL_ID` | 模型 ID | `deepseek-chat` |
| `FALLBACK_MODEL_ID` | 过载时降级模型 | (可选) |

## 设计原则

- **依赖注入**：`main.py` 通过 `AgentLoopDeps` 显式注入外部能力到 `agent_loop.py`，执行引擎不 import 入口层
- **单向依赖**：`agent_loop.py` 不依赖 `main.py`，核心逻辑可独立测试
- **权限优先**：所有工具调用经过 `PreToolUse` hook → `PermissionManager` 检查
- **上下文控制论**：多级自适应压缩策略自动管理上下文窗口

## 测试

```bash
python -m pytest tests/ -v
```
