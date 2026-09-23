# ai-chat-app-main 项目交接文档

项目目录：D:\github\ai-chat-app-main

## 技术栈

- 前端：Vue 3、Vite、TypeScript、Tailwind CSS、Vue Router
- 后端：Python、FastAPI
- 数据库：PostgreSQL；原 SQLite 文件 backend/data/ai_chat.sqlite3 保留
- 向量数据库：ChromaDB
- 模型：DeepSeek、OpenRouter（OpenAI-compatible API）

## 已完成能力

1. LLM Provider 解耦：统一 Provider、LLMResponse、LLMUsage；DeepSeek 和 OpenRouter 支持普通聊天、Streaming、模型切换。
2. Token Usage：普通聊天、Tool Calling 多轮调用、RAG 请求统一累计并写入 PostgreSQL。
3. PostgreSQL：SQLite → PostgreSQL 已迁移，业务表包括 chat_messages、token_usage、workspaces、chat_sessions。
4. 聊天接口：POST /chat、POST /chat/stream、GET /sessions、GET /sessions/{session_id}/messages、PATCH /sessions/{session_id}、DELETE /sessions/{session_id}。
5. RAG：文件上传、解析、chunk、embedding、ChromaDB 索引、真实 Citation sources、文件状态 indexed/failed/not_indexed、文件删除同步向量。
6. Workspace：创建、切换、编辑、删除；会话和 RAG 数据按 workspace 隔离。
7. 本地状态：session_id 和 model_id 使用 localStorage；New Chat 使用 crypto.randomUUID()。
8. 历史会话：列表、切换、删除、标题重命名；手动标题优先于首条 user 消息。

## 最近完成的 Chat UI

当前结构：

    ChatPage
    ├── MessagesViewport（独立滚动）
    └── ComposerDock（聊天区域底部）
        └── MessageComposer

- Chat 页面限制在视口高度内，只有消息区滚动。
- Composer 不随消息滚走，不覆盖 Sidebar。
- Composer 左下：添加文件、ModelSelector。
- Composer 右下：Settings、Send/Stop。
- New Chat 已从 Chat 顶部移到 Sidebar 历史记录标题右侧。
- 消息区保留轻量当前标题和重命名入口。
- 移动端无横向溢出。

## 关键文件

前端：

- frontend/src/App.vue：Sidebar、Workspace、历史会话、New Chat、Chat 视口约束
- frontend/src/pages/ChatPage.vue：消息区、ComposerDock、文件上传、标题编辑
- frontend/src/components/chat/MessageComposer.vue：textarea、自动增长、发送/停止
- frontend/src/components/chat/ModelSelector.vue：自定义模型下拉
- frontend/src/lib/chat.ts：session、model、聊天请求、Streaming、历史状态

后端：

- backend/app/core/database.py：SQLite/PostgreSQL 抽象、业务表、聊天和 usage 持久化
- backend/app/api/routes/chat.py：聊天、Streaming、RAG、Tool Calling
- backend/app/api/routes/history.py：会话列表、消息、标题、删除、usage summary
- backend/app/providers/base.py：统一 Provider 返回结构
- backend/app/providers/deepseek.py：DeepSeek
- backend/app/providers/openrouter.py：OpenRouter
- backend/app/providers/factory.py：Provider 工厂
- backend/app/rag/：loader、chunk、embedding、ChromaDB、检索和 Citation

## 主要 API

    GET  /health
    GET  /models
    POST /chat
    POST /chat/stream
    GET  /sessions?workspace_id=...
    GET  /sessions/{session_id}/messages?workspace_id=...
    PATCH /sessions/{session_id}?workspace_id=...
    DELETE /sessions/{session_id}?workspace_id=...
    GET  /usage/summary
    POST /files/upload
    GET  /files
    DELETE /files/{filename}
    GET/POST/PATCH/DELETE /workspaces...

## 环境变量

敏感值只放 backend/.env，不要打印、提交或写入源码。

    DATABASE_URL=postgresql://...
    OPENAI_API_KEY=...
    OPENAI_BASE_URL=...
    OPENAI_MODEL=...
    OPENROUTER_API_KEY=...
    OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
    OPENROUTER_MODEL=openrouter/free

Embedding Provider 与聊天 Provider 已解耦，不能把 DeepSeek 聊天 Key 当作 Embedding Key。

## 启动

终端 1：

    cd /d D:\github\ai-chat-app-main\backend
    .venv\Scripts\activate
    uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

终端 2：

    cd /d D:\github\ai-chat-app-main\frontend
    npm run dev

前端：http://127.0.0.1:5173/chat
后端：http://127.0.0.1:8000
Swagger：http://127.0.0.1:8000/docs

## 验证状态

- 后端自动测试：36/36 通过
- TypeScript 检查：通过
- npm run build：通过
- 浏览器已验证消息独立滚动、Composer、模型切换、Settings、文件上传/RAG、Streaming/Stop、New Chat、历史切换、标题重命名和移动端布局。

## 暂未开始

Agent、长期记忆、Workspace 高级协作、Streaming 断点恢复。

## 新对话起始提示词

    继续开发 D:\github\ai-chat-app-main。
    请先阅读 docs/ai-chat-app-handoff.md。
    当前已完成 Provider、DeepSeek/OpenRouter、Token Usage、PostgreSQL、RAG/Citation、Tool Calling、Workspace、localStorage、历史会话、标题重命名，以及 Chat 消息独立滚动和 Composer Dock。
    只处理我接下来明确提出的任务，不要重复修改已完成的核心逻辑。
    先分析相关文件，再做最小修改，并运行 TypeScript、Vite build 和后端测试。
