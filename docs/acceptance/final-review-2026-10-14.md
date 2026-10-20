# Citation 与网络隔离：最终审查及待确认提交计划

日期：2026-10-14。仓库：`D:\github\ai-chat-app-main`。

## 结论

本轮要求的自动化回归全部通过；但额外的纯本地兼容性检查发现一个普通聊天误拦截问题，建议先修复再提交 Citation 部分。网络隔离部分可单独提交。尚未执行 git add、commit、push，也未访问真实 Exa、DeepSeek 或 OpenRouter API。

分支仍为 `feat/agent-core`，HEAD 为 `f14e83eb069d039e043d6b48b1c40895ec661381`。原暂存区为空，本轮没有修改暂存区、main 或已有业务代码。本轮仅新增本报告，保留所有既有未提交改动。

## 审查发现：[P2] 普通数字数组被当成非法引用

位置：`backend/app/services/citations.py:103`。

`CitationStream.feed()` 把代码区之外的所有纯数字方括号统一当成未绑定的引用。`CitationRegistry` 即使没有来源也使用该检查，且普通聊天、流式聊天与 Agent 都会进入此校验器。因此合法的普通文本也会失败。

纯本地复现（只导入解析器，不使用 Provider 或配置密钥）：

| 输入 | 实际结果 |
| --- | --- |
| `列表为 [1, 2]。`，空来源目录 | 抛出 `CitationError: Unbound numeric citation; use the source catalog marker` |
| 数组在反引号代码区中 | 原样通过 |
| 普通无括号回答 | 原样通过 |

这不说明已有 134 项测试失败，而是说明现有测试没有覆盖该兼容情形。建议新增普通数字文本回归，并明确“普通内容”和“引用标记”的识别规则，同时保留未知 `[[cite:...]]`、不存在引用编号及流式分块的约束。仅靠 Prompt 要求模型给数组加反引号不能作为可靠修复。

本轮是最终审查，未擅自修改解析规则，也未删除或放宽测试。Citation 提交建议暂缓。

## 本轮实际测试

| 检查 | 命令/范围 | 结果 |
| --- | --- | --- |
| 完整后端 | `python -m pytest -x` | 134 passed、62 subtests passed，17.06 秒 |
| 网络隔离自检 | `python -m pytest -x app/tests/test_network_isolation.py` | 10 passed，1.62 秒 |
| Citation 自检 | `python -m pytest -x app/tests/test_citations.py` | 10 passed、56 subtests passed，3.06 秒 |
| 相关组合回归 | 网络隔离、Citation、Chat stream、Chat usage、Agent orchestrator、Persistence 六个测试文件 | 63 passed、56 subtests passed，5.88 秒 |
| 前端 TypeScript | 本地 `vue-tsc --noEmit` | 通过 |
| 前端构建 | `npm.cmd run build`（包含 `vue-tsc -b`） | 通过；Vite 构建 14.53 秒 |
| 差异格式 | `git diff --check` | 通过 |
| 普通数组兼容性 | 纯本地解析调用 | 未满足预期：误拦截，详见审查发现 |

测试在现有 autouse fixture 下运行：运行时 Provider 凭据清空、Embedding 替身、网络拦截启用。测试代码里的 `test-key` 等为模拟值。本轮没有执行真实搜索、模型推理、账户额度查询或模型目录查询。

pytest 有现有 Starlette/anyio 弃用警告；Vite 有现有大 chunk 警告，均未阻止构建。没有运行依赖安装、浏览器或实际 TCP 六场景回放；此前报告中的这些结果保持为历史验收证据，不计作本轮重跑。

## Git、敏感信息与设计审查

- 审查覆盖 9 个已跟踪修改文件和 10 个未跟踪文件，含文本 16 个、PNG 3 个。本报告新增后，拟讨论的文件总数为 20。
- 差异对应原设计：来源注册与去重、稳定 ID、流式转换、非法引用拒绝、来源持久化、Sources 可见编号、历史恢复、测试隔离及回放资料。
- 没有意外删除，没有新增依赖或修改锁文件，没有断点、`pytest.skip` / `xfail` 或跳过测试装饰器，没有发现与本任务无关的业务改动。
- 对候选文本执行凭据模式扫描：常见 OpenAI/OpenRouter/GitHub/AWS 密钥、私钥块、凭据字面量及带用户名密码的 URL，命中 0；结合人工差异审查，未发现真实凭据或敏感日志。模式扫描不能作为绝对无泄漏证明。
- 三张截图均已本地查看，内容为回放提示、公开项目来源及合成知识片段，未发现密钥或私人聊天内容。
- `.env` 未被读取以取得密钥，也未被修改；`git ls-files backend/.env frontend/.env` 无输出。数据库、日志、缓存、venv、node_modules、dist 均不在候选文件中；git ignore 检查确认对应路径被忽略。
- SQL 使用新增列、默认空来源及参数化保存，没有删除或重写用户历史的代码；实际 PostgreSQL 迁移尚未验收，SQLite 路径有回归覆盖。

## 网络隔离边界

已验证 HTTPX 同步/异步默认 transport、DNS getaddrinfo、TCP connect/connect_ex、UDP sendto、urllib 的 HTTP/HTTPS 回环代理目标检查、DDGS 代理/实现类构造拦截，以及 MockTransport/回环 DNS/ASGI 兼容性。

未覆盖通用 import/collection 阶段、fixture 前已建连接或 DDGS 实例、其他原生 C/Rust 网络客户端、其他 DNS API、已有连接 send/sendall 和任意自定义代理协议。该 fixture 是当前常规测试的保护设施，不是 OS 级断网或任意程序沙箱。详细复现见 `network-isolation-2026-10-14.md`。

## 建议的两个逻辑提交

以下仅为待确认计划，没有执行暂存或提交。建议先提交隔离保护，再提交依赖它运行验收的 Citation 修改。

### 提交一：网络隔离（4 个文件）

建议信息：`test: isolate provider traffic and guard loopback proxy escapes`

```text
backend/conftest.py
backend/app/tests/test_network_isolation.py
backend/app/tests/test_persistence.py
docs/acceptance/network-isolation-2026-10-14.md
```

其中持久化测试只增加搜索 Mock 和调用断言，属于防止意外消耗额度的隔离修复。该提交内容可独立考虑提交。尚未在隔离出的单独提交树上运行测试，不能把整棵工作区通过视作两个中间提交分别通过。

### 提交二：Citation（16 个文件，建议先修复审查发现）

建议信息：`fix: bind streamed citations to stable persisted sources`

```text
backend/app/services/citations.py
backend/app/agents/orchestrator.py
backend/app/api/routes/chat.py
backend/app/api/routes/chat_stream.py
backend/app/core/database.py
backend/app/models/chat.py
backend/app/tests/test_chat_stream.py
backend/app/tests/test_citations.py
backend/scripts/serve_citation_replay.py
frontend/src/lib/chat.ts
frontend/src/components/chat/MessageBubble.vue
docs/acceptance/citation-acceptance-2026-10-13.md
docs/acceptance/citations-browser-2026-10-13.png
docs/acceptance/citations-cancel-2026-10-13.png
docs/acceptance/citations-failure-2026-10-13.png
docs/acceptance/final-review-2026-10-14.md
```

原 Citation 验收报告引用了网络隔离措施，置于第二提交可避免文档先于隔离实现。最终报告随第二提交保存。普通数组问题修复后，应更新本报告、重跑相关测试，再对实际 staged diff 重新扫描；只有用户确认后才提交与推送。推送前还需检查远端分支状态，不强推、不修改 main、不合并 PR。

## 下一轮真实模型验证建议（本轮未执行）

先解决普通内容误拦截，再向用户申请明确预算：最多 2 个只读元数据 GET（固定模型报价、当前 Key 额度）和 1 个固定模型流式推理 POST。认证信息只留在请求头，不记录或输出。

只有在当时的元数据确认固定 `:free` 模型报价为 0、额度条件允许时，才运行那 1 次推理；禁用 SDK 自动重试，不切换收费模型或默认 DeepSeek，不启用付费插件，也不发送真实 Exa 搜索请求。使用已存公开资料及合成知识片段，设置明确输出上限。

一个最小样例同时包含来源重排、重复 URL、Web/知识混合和模型倾向自行编号的提示。逐增量检查标记转换，核对最终可见编号、Sources URL 和保存文本；检查不存在编号及目录外标记。同步记录实际请求次数、Usage、耗时和失败原因。该样例可证明一次真实模型对最终回答协议的遵循情况，不能替代完整真实 Agent Tool Calling 或长期稳定性验收。
