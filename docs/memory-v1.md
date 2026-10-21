# Long-term Memory V1

> V1.1 已补充 Settings 管理与只读生命周期预览，参见 [Memory V1.1](memory-v1.1.md)。下文保留 V1 原始实现和当时验收记录。

## 范围与架构

| 类型 | 数据与用途 | 当前实现 |
| --- | --- | --- |
| Chat History | 某次会话用户和助手的原始消息，按 Session 恢复 | 业务数据库 `chat_sessions` / `chat_messages`，前端发送当前对话历史 |
| RAG Knowledge | 用户上传文件的可追溯证据，包含文档/片段/页码与 Citation | documents 元数据 + Chroma 文档集合，已有检索及读取工具 |
| Long-term Memory | 用户明确确认、在同一 Workspace 跨 Session 保留的简短信息 | 独立 `MemoryService` + 单独 SQLite 文件，显式 CRUD API，确定性关键词检索 |

本轮新增记忆服务和 API，普通 Chat、SSE 和 Agent 共用上下文注入。没有自动提取、向量检索、后台任务、模型记忆写工具、UI 管理页或多 Agent 共享；不把记忆写入 RAG/Chroma，不把记忆作为 Citation 证据。

数据流：用户明确确认的 API 操作 → MemoryService → 独立 SQLite；新的聊天请求 → 现有 Workspace/Session 归属校验 → 检索当前 Workspace 相关记忆 → 受预算限制的 JSON 上下文 → 原有 Provider/Agent → 原有答案和 Usage 流程。

## 默认关闭及数据库边界

配置示例（仅供独立本地测试，不会自动写入现有 `.env`）：

```ini
MEMORY_ENABLED=false
MEMORY_DATABASE_PATH=./data/memory.sqlite3
MEMORY_CONTEXT_TOKEN_BUDGET=512
```

- 默认关闭：不打开记忆存储，不创建记忆文件；记忆 API 返回 503。现有 Chat 不增加模型调用，不改变工具列表。
- 显式启用后仅使用配置的独立 SQLite 文件；不使用业务 `DATABASE_URL` 执行记忆 DDL。拒绝 URL、内存路径、已配置业务 SQLite 路径，以及包含其他表/不支持版本或列的数据库文件，不自动升级未知数据库。
- 新文件懒初始化 `memories` 表及 `PRAGMA user_version=1`。读写使用参数化 SQL 和事务，最多 200 条/Workspace。未改变业务表、现有会话或 Chroma Collection。
- **本轮没有连接、备份、迁移或写入用户 PostgreSQL。** API 路由和聊天本身仍沿用现有业务数据库的 Workspace 校验；离线测试将该数据库也换为临时 SQLite，不启动用户的后端服务进行联调。

## SQLite 数据设计

| 字段 | 约束/含义 |
| --- | --- |
| id | TEXT 主键，服务端 UUID |
| workspace_id | TEXT NOT NULL，每条查询/修改都必须显式限定 Workspace |
| key | 归一化的记忆主题；NFKC、casefold、合并空白；最多 80 字符 |
| value | 用户确认的值；NFKC、首尾去空白，最多 1,000 字符；拒绝空值/NUL |
| version | INTEGER >= 1，实际修改时递增，用于防止覆盖并发更新 |
| created_at / updated_at | UTC ISO 时间戳，仅供记录，不用于耗时计算 |

唯一约束 `(workspace_id, key)` 同时提供 Workspace 前缀索引。由于 SQLite 记忆文件和业务库分离，不能建立跨库外键；API 在访问记忆前检查 Workspace 存在，聊天在注入前复用 `resolve_workspace_request()` 的归属检查。

### 重复与冲突规则

1. 同 Workspace、归一化 key 和 value 相同：幂等返回现有记录，不增加版本或更新时间。
2. 同 Workspace、同 key、value 不同：创建返回 409，不静默覆盖。不同主题 key 不做语义冲突推断，也不合并。
3. 更新必须提供 `confirmed=true` 和当前 `expected_version`；过期版本返回 409。key 不可改名；同值更新不增版本。
4. 删除必须提供当前 `expected_version`，过期返回 409；不存在或属于其他 Workspace 的 ID 返回 404。物理删除后下次检索不再返回。
5. 创建和更新缺少确认、`false`、非布尔确认或未知字段均拒绝。事务使用 `BEGIN IMMEDIATE`，确保同键检查、容量检查与写入之间没有并发窗口。

## 用户操作 API

路径前缀：`/workspaces/{workspace_id}/memories`。写操作仅来自用户明确提交，模型未注册任何 memory 写工具，不会根据普通聊天中的“记住”自动创建记忆。

| 方法 | 路径/参数 | 行为 |
| --- | --- | --- |
| POST | 前缀，`{"key":"preferred_language","value":"中文","confirmed":true}` | 创建或幂等返回，200 |
| GET | 前缀，`?q=preferred_language&limit=100&offset=0` | 列表或词项匹配查询；limit 1–200，查询最多 500 字符 |
| GET | `/{memory_id}` | 当前 Workspace 下按 ID 查询 |
| PATCH | `/{memory_id}`，`{"value":"English","expected_version":1,"confirmed":true}` | 用户确认的版本化更新 |
| DELETE | `/{memory_id}?expected_version=2` | 删除，204；不返回内容 |

没有新增身份认证/多用户授权机制；Workspace 隔离沿用当前本地单用户应用的 ID 作用域约束，不代表具备互联网多租户安全边界。不存在的 Workspace 或其他 Workspace 的记忆 ID 不暴露数据。

## 跨会话检索与严格上下文上限

- 不按 Session 筛选记忆，只按当前已校验的 Workspace；没有显式 Workspace 不注入。
- 取最新用户问题的前 500 字符；英文/数字/下划线词项和中文连续双字词项做集合交集计数。仅选择有重叠的记忆，按重叠数降序、key 升序稳定排序，无命中不退回“注入全部记忆”。
- 最多注入 3 条完整记忆。V1 扫描每 Workspace 最多 200 条的集合；不创建缓存或向量索引。
- 预算默认 512，允许 0–2048；0 禁用注入。对**完整新增消息 JSON 的 UTF-8 字节数 + 64 framing 预留**实施硬上限。逐条尝试，超限项跳过，不截断句子或偷偷扩大预算；预算太小就不注入。
- 该字节约束是 byte-level tokenizer 的保守 Token 上界，不是调用真实 tokenizer 得到的精确计数；未知 Provider 的归一化/聊天模板仍需真实模型验收，不能宣称测得真实 Token。包含固定安全策略和角色封装的预算测试覆盖中英文及超长内容。
- Agent 一次 Run 只检索一次快照，规划、行动和最终回答复用。已有 Agent 整体 Token 预算仍覆盖包含记忆的模型请求；Usage 继续来自现有 Provider，不伪造额外消耗，也不增加模型调用次数。

## 不可信数据与安全边界

固定、服务端写死的 system 策略声明记忆仅为上下文、不得覆盖系统/用户请求或赋予权限；具体 key/value 仅放在 `role=user` 的 `WORKSPACE_MEMORY_JSON` 中，并由 JSON 转义。任何内嵌 `role=system`、命令或伪造工具格式都保持普通字符串，不转换为角色、工具或执行代码。

这保证服务端消息结构和工具权限不会因记忆数据提升，不是对真实 LLM 语义 Prompt Injection 的绝对免疫证明。工具注册、参数校验及 Workspace 检查仍由原有服务端执行；未给模型任何记忆写入口。记忆故障时聊天以通用日志提示并跳过记忆，不记录值或完整 Prompt；管理 API 返回明确 503。

注入消息不会额外保存成 Chat History、Sources 或 Agent Step。用户原本发送的内容和模型最终回答仍按原有机制保存，模型可能在回答中复述相关记忆；不是加密隐私存储。

## 迁移、备份与回滚方案（未在生产执行）

### 独立 SQLite

1. 启用前确认路径是专用新文件，和业务数据库不同；由管理员限制文件访问权限。默认路径已被 Git ignore。
2. 已有 sidecar 如需升级，先停写，通过 SQLite `Connection.backup()` 复制到仓库外备份文件；在独立副本执行 `PRAGMA integrity_check`，核对行数、Workspace、key/value 和版本，再进行恢复演练。不要在数据库仍写入时简单复制单个主文件而忽略 journal/WAL。
3. 本轮仅版本 1 初始化，不包含版本升级。未知模式拒绝访问，不删除或重建。
4. 应用回滚：先设 `MEMORY_ENABLED=false` 并重启，经确认恢复上一应用提交；保留 sidecar 和备份，不 DROP 或覆盖数据。恢复数据只在另一个专用路径验证后，经单独确认切换路径。

离线测试已通过 SQLite backup → 独立目标副本 → integrity_check → 记录/版本核对，原文件记录不变。这不等于用户 PostgreSQL 恢复验收。

### 未来 PostgreSQL（仅设计）

生产迁移仍被“用户 PostgreSQL 独立恢复未完成”阻断。V1 **没有 PostgreSQL Memory 实现、DDL 执行脚本或启动迁移钩子**。未来方案：

1. 管理员提供独立恢复数据库，验证现有备份、聊天/Sources/Workspace 完整性；先在副本验收，再请求用户单独批准生产迁移。
2. 增量新增 `workspace_memories` 表：同上字段，`workspace_id` 引用 `workspaces(id)`，`ON DELETE CASCADE`，唯一 `(workspace_id,key)`，version 检查约束及 schema 版本记录；不修改聊天和 Chroma 数据。
3. 在一个事务中创建新表/索引/迁移记录；如已存在同名对象，核对结构后停止或按审核后的迁移处理，不使用无条件 DROP/重建。导入 sidecar 前核对所有 Workspace 仍存在，未知 Workspace 进入人工处理，不自动改归属。
4. 导入到临时/新表后按 ID、内容、版本及各 Workspace 行数验证；并发写入采用版本条件 UPDATE，确认所有检查通过后再切换显式存储配置。不得把 SQLite 路径替换成 PostgreSQL URL 来“启用”。
5. 回滚优先关闭 Memory / 恢复旧应用配置，保留新增表。只有备份已验证、数据导出且另行获批准后才考虑删除新增表；不逆向改写旧业务数据。

## 验证与复现

```powershell
Set-Location backend
.venv/Scripts/python.exe -m pytest -q -o addopts= app/tests/test_memory.py
# 完整回归
.venv/Scripts/python.exe -m pytest -o addopts=
```

全部 Memory 测试使用临时 SQLite、临时 storage/Chroma 和 Mock Provider。覆盖 CRUD、显式确认、重复/冲突、过期版本、删除后不检索、跨 Session、四条 Chat/Agent 同步/流式路径、Workspace 越界拒绝、中文检索、预算、恶意内容结构、默认关闭无数据库访问、独立文件防误用、存储不可用降级、禁止业务连接与 SQLite 备份恢复。

本地实测：Memory 针对性 **22 passed**；完整后端 **187 passed**（27.74s）；`npx vue-tsc --noEmit` 和 `npm run build` 通过，仅保留原有 Starlette/anyio 弃用和 Vite 大包警告。GitHub CI 以该提交的 PR 检查记录为准。

没有真实 LLM、Exa 或 Embedding 调用，没有浏览器 Memory UI 验收。

## 剩余限制

- **用户 PostgreSQL 尚未迁移；真实模型尚未验收。** 默认保持关闭，不自动修改 `.env` 或重启服务。
- 管理入口仅为 API，没有新增前端记忆管理界面或自然语言记忆命令。
- 关键词检索无语义理解，同义词可能漏召回，超长记录可能因预算永不注入；精确 key 查询可用于稳定读取。
- 独立存储没有跨库事务/外键。删除 Workspace 后原记忆可能保留为不可通过 API 访问的孤立记录；不自动删除用户数据。导出/清理及未来外键迁移需另行设计确认。
- 删除影响后续检索；已开始的 Run 快照以及先前回答中复述的信息不会被追溯抹除。备份恢复可能重新带回已删除记录，恢复前必须核对。
- 文件未加密、未实现敏感信息检测。仅保存用户明确确认且适合持久保留的信息，部署方需配置磁盘权限和保留策略。
