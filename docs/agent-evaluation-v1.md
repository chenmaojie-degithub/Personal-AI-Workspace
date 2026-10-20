# Agent Evaluation V1

## 范围与结论

固定的离线回归基线，验证当前路由、Agent 循环、工具参数校验、Citation 和运行记录；不引入评测框架或 LLM Judge，也不修改运行时代码。

本次 **12/12 场景通过**，工具序列匹配 **12/12**，禁止工具实际执行 **0** 次。流向前端的引用 **8/8** 通过编号与来源身份校验。错误场景按正确拒绝、失败或取消判断通过，不表示所有任务都生成了答案。

**固定测试通过率不等于真实开放任务成功率；引用结构正确不等于事实正确。** Provider 的行动和最终输出由脚本控制，不证明真实模型的规划、恢复或语义判断能力。

## 资产与实现

- [固定输入与独立预期](../backend/app/tests/fixtures/agent_evaluation_v1.json)：12 个固定问题、模型动作、预期工具序列、来源身份、调用次数和终态。
- [评测与评分器](../backend/app/tests/test_agent_evaluation.py)：复用已有 `test_agent_orchestrator.Provider`、Usage helper 与 Citation catalog helper；增加 3 个评分器防错测试。
- [机器结果](evaluation/agent-evaluation-v1.json)：schema/suite 版本、执行时 HEAD、源码 SHA-256、生成时间、逐项 checks 和指标。报告导出仅在显式设置环境变量时发生，普通 pytest 不覆盖基线。
- 实际调用 `_routed_events()`、Agent Orchestrator、Tool Registry 校验与执行、CitationRegistry、取消接口及数据库持久化函数。所有搜索和文档内容都是合成的；每个场景使用 pytest 临时目录内独立 SQLite、storage、Chroma 路径。
- 沿用全局离线测试保护；不连接真实 Exa/LLM/Embedding 或用户 PostgreSQL。保护为测试层机制，不是操作系统网络沙箱。

## 场景输入、目标与通过条件

工具简写：W=`search_web`，K=`search_knowledge`，∅=不执行工具。以下序列指通过服务端校验后进入 handler 的实际执行序列；抛错的 handler 仍算执行。

| 场景 | 固定输入 | 预期行为与通过条件 | 预期实际工具 |
| --- | --- | --- | --- |
| `simple` | Explain what a variable is. | 简单聊天直接流式回答，不额外规划或调用工具。 终态 `completed`。 | ∅ |
| `web` | Research the latest web release. | 调用一次网页搜索，回答引用工具提供的 Gamma 来源。 终态 `completed`。 | W |
| `rag` | Compare facts in the knowledge document. | 调用知识检索，引用合成文档 local-doc 的片段 0。 终态 `completed`。 | K |
| `mixed` | Research and compare web sources with knowledge documents. | 网页与知识混用，来源身份和引用顺序必须正确。 终态 `completed`。 | W → K |
| `tool_recovery` | Research the web and compare knowledge evidence after failure. | 网页工具故障后继续知识检索，保留失败观察并最终完成。 终态 `completed`。 | W → K |
| `invalid_tool` | Research the web and verify with knowledge documents. | 额外参数被真实 Schema 拒绝；注入文本工具格式错误，最多一次受控修复后执行合法工具。 终态 `completed`。 | K |
| `citation_identity` | Research and compare web and knowledge sources with repeated searches. | 同参数重复搜索一次，重复 URL 不增号，Gamma=3、知识来源=4。 终态 `completed`。 | W → W → K |
| `invalid_citation` | Research the latest web release and compare sources. | 模型伪造【999】，服务端拦截，不泄露错误编号或保存失败回答。 终态 `failed`。 | W |
| `budget` | Research the latest web release. | 规划消耗固定预算后停止，不启动工具或额外模型调用。 终态 `budget_exceeded`。 | ∅ |
| `cancel` | Research and compare the latest web sources. | 首段文本出现后主动取消，无后续工具且不保存半截回答。 终态 `cancelled`。 | W |
| `workspace_denied` | Compare the attached knowledge documents. | 当前 Workspace 关联另一 Workspace 的文档，真实归属检查在模型/工具前拒绝。 终态 `failed`。 | ∅ |
| `disabled_tool` | Research the latest web release. | Workspace 关闭网页搜索且请求不覆盖设置；模型仍请求搜索时必须拒绝执行。 终态 `completed`。 | ∅ |

所有场景还检查：路由、终态、模型调用次数、Observability 与 Provider 记录一致、无禁止执行、无控制标记泄露、来源完整有序、所需引用存在、消息保存次数及 done 事件。完成答案仅保存一次；取消/失败不保存半截答案；预算耗尽可保存明确的终止说明。

### 合成来源及引用身份

网页固定顺序为 `https://example.test/alpha`、`/beta`、`/gamma`；每次工具结果还重复 Alpha，验证同次及跨次去重。知识来源身份为 `local-doc` / chunk 0，page 1。混合场景要求 Gamma 对应编号 3、知识来源编号 4。`.test` URL 仅为测试数据，不代表真实搜索或可访问网站。

评分预期来源独立保存在 fixture 中，不从实际结果反推。Mock 最终生成使用真实注册表 marker，按 8 字符切分 SSE 文本；评分器同时验证完整来源目录与正文编号映射。额外负例证明：现存编号绑定错误 URL、未知编号都不能得分；无引用保持 null。

## 本次实测结果

生成时间：`2026-10-20T07:51:27.925405+00:00`。运行时代码基线：`6aacb437eb888d0e9ada7290bf326c377c6d366c`。评测代码当时尚未提交，精确版本由 JSON 的 `source_sha256` 标识；运行时代码未修改。

| 场景 | 结果 / 实际终态 | 模型调用 | Mock Token 总计 | 运行耗时 ms | 有效引用 / 已输出引用 |
| --- | --- | ---: | ---: | ---: | ---: |
| `simple` | PASS / `completed` | 1 | 6 | 16.000 | 0/0 |
| `web` | PASS / `completed` | 4 | 36 | 63.000 | 1/1 |
| `rag` | PASS / `completed` | 4 | 36 | 63.000 | 1/1 |
| `mixed` | PASS / `completed` | 5 | 46 | 94.000 | 2/2 |
| `tool_recovery` | PASS / `completed` | 5 | 46 | 109.000 | 1/1 |
| `invalid_tool` | PASS / `completed` | 6 | null | 93.000 | 1/1 |
| `citation_identity` | PASS / `completed` | 6 | 56 | 125.000 | 2/2 |
| `invalid_citation` | PASS / `failed` | 4 | null | 47.000 | 0/0 |
| `budget` | PASS / `budget_exceeded` | 1 | 10 | 31.000 | 0/0 |
| `cancel` | PASS / `cancelled` | 4 | null | 62.000 | 0/0 |
| `workspace_denied` | PASS / `failed` | 0 | null | 15.000 | 0/0 |
| `disabled_tool` | PASS / `completed` | 4 | 36 | 47.000 | 0/0 |

- 场景通过率、工具匹配率：100%。模型逻辑调用合计 44 次，包含规划、行动、修复、最终流式生成与失败尝试，不等于外部 HTTP 请求次数。
- 被拒绝的工具请求 2 次：非法参数、禁用搜索。均未执行 handler；这与“禁止工具实际执行 0 次”分别统计。文本解析错误发生于 dispatch 前，计入模型失败尝试，不计为 handler 拒绝。
- 重复工具请求 1 次：`citation_identity` 特意重复同工具同参数，以评测跨搜索的引用去重；这是已观测到的重复，不宣称 Agent 完全抑制重复。
- 8 个已输出引用全部有效，结构正确率 100%；无引用场景的比率为 null，不按 100% 填充。`invalid_citation` 拒绝非法编号后不输出该引用，另以终态、错误类型和禁止保存条件验收，不能仅凭引用正确率判断。
- 4 个场景 Usage 未知，汇总总量为 null；其余场景已知小计 219 input + 53 output = 272 Mock Token。不是完整消耗、真实 tokenizer 测量或服务账单。费用未估算；本轮真实 API 请求 0 次。

### 本地验证

- 针对性测试：15 passed（12 个场景 + 3 个评分器防错用例）。
- 完整后端：165 passed，19.25s；保留原有 Starlette/anyio 弃用警告。
- `npx vue-tsc --noEmit`：通过；`npm run build`：通过，保留原有 Vite 大包警告。
- 无应用运行时代码、数据库结构、用户数据或配置变更。GitHub CI 状态以该提交的 PR 检查为准，不以本地结果替代。

## 指标定义

| 指标 | 定义与边界 |
| --- | --- |
| 场景通过率 | 所有场景 checks 同时满足的场景数 / 固定场景总数；失败保护场景正确拒绝也计通过。 |
| 工具匹配率 | 实际进入 handler 的工具名有序序列与 fixture 预期完全一致的场景比例；参数通过真实 Schema 校验。它不衡量任意参数的语义正确性。 |
| 禁止执行次数 | handler 执行时不在该场景许可工具集中，或被记录的 Workspace 不匹配；结合真实跨 Workspace 文档归属负例。 |
| 拒绝请求次数 | 已请求 dispatch 但被校验/注册条件阻挡、尚未进入 handler 的请求次数。 |
| Citation 结构正确率 | 正文 `【n】` 能映射到独立预期的第 n 个来源身份的数量 / 正文引用数量；还单独检查目录顺序、编号连续性、来源去重及必要引用。无引用为 null。 |
| 重复请求次数 | 同工具名 + 参数 JSON（键排序）签名重复次数，每个签名第一次不计；包括被拒绝的 dispatch 尝试。 |
| 模型调用次数 | Mock complete/stream 入口次数，包括失败、修复；Agent 场景与已持久化 Observability 计数交叉验证。 |
| Token Usage | Agent Observability 的累计值；直接聊天使用 usage SSE。任一模型调用 Usage 不可得时，该场景为 null；总汇总也为 null，已知小计另列。 |
| 运行耗时 | Agent 场景复用 `metrics.duration_ms` 的 monotonic 测量；没有 Run 的直接回答/入口拒绝测 `_routed_events` 消费时长，JSON 的 duration_scope 区分。包含本地数据库/消费等待。 |

这些耗时为单次离线 Mock 实测，受系统时钟分辨率、文件系统、调度影响，不设性能阈值；不代表真实 LLM/Search 的 TTFT、延迟或 SLA。

## 如何复现

在仓库根目录打开 PowerShell（先安装项目后端依赖），然后：

```powershell
Set-Location backend
.venv/Scripts/python.exe -m pytest -q -o addopts= app/tests/test_agent_evaluation.py
```

默认运行 12 个场景 + 3 个评分器防错用例，不写结果文件。显式导出用于版本比较：

```powershell
$env:PAW_AGENT_EVAL_OUTPUT = Join-Path $env:TEMP 'paw-agent-evaluation-v1.json'
.venv/Scripts/python.exe -m pytest -q -o addopts= app/tests/test_agent_evaluation.py
Remove-Item Env:PAW_AGENT_EVAL_OUTPUT
```

仅当完整 12 个场景运行完毕才允许导出，避免把 `-k` 子集误当完整基线。审阅前保留原 JSON；比较 suite_version、fixture/source hashes、checks、工具序列、计数和 null 情况。固定预期故意严格：合法行为改变时先审阅差异，再更新版本及基线，不能直接用实际结果覆盖 gold。耗时可观察变化，不与旧机器做精确数值断言。

CI 的完整 pytest 自动包含本套评测，不需要真实密钥、用户数据库或单独服务。正式更新仓库基线时把输出路径改成 `../docs/evaluation/agent-evaluation-v1.json`，同时更新本说明中的实测数据，并审阅差异。

## 已知限制

- 脚本化 Provider 与工具结果验证的是引擎执行契约，不覆盖真实模型的选择质量、真实 Exa 检索相关性、Embedding/Chroma 召回率、答案事实性、恶意网页语义注入或真实费用。
- 工具失败恢复是固定合法动作脚本，不证明模型自主恢复。文本工具错误以 Provider 抛出的既有解析异常模拟；具体文本解析格式仍由原有 Parser 单测负责。
- Workspace 负例覆盖真实文档归属检查及无请求覆盖时的持久化工具开关，不是全面安全审计，也未新增更严格的权限策略。
- 取消在首段可见文本后通过真实 run_id 发起；检查 cancelled、无额外工具及不保存半截回答，不模拟真实网络断开/浏览器 Abort 的全部竞态。
- SSE 测试消费实际路由生成器，不经过 TCP HTTP 或浏览器；本轮没有新增浏览器、真实 PostgreSQL 迁移/恢复或真实 API 验收。
- 没有引入线上评测、成本估算、复杂 Dashboard、长期记忆、工作流。后续如要比较真实模型，需另行批准预算并使用独立结果，不能替换本离线基线。
