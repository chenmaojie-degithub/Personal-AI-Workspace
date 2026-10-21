# Agent Observability V1

## 范围

复用现有 Agent 执行、agent_runs/agent_steps、Provider Usage、运行详情接口与 SSE。不增加 Dashboard、外部监控依赖、长期记忆或工作流。普通 Chat 路由不采集 Agent 指标，执行策略和工具权限不变。

## 指标定义

| 字段 | 定义与采集点 | 精度/未知值 |
| --- | --- | --- |
| duration_ms | run_agent 开始到最终回答保存完成或异常/取消被执行器观察到；RunObservation 使用 monotonic 差值 | 服务端墙钟经过时间，非浏览器端到端；运行中是事件时刻快照 |
| ttft_ms | 开始到第一个通过 Citation 校验、非纯空白的 message 增量即将 yield | 首段可见文本等待，不是供应商原始首 Token；无文字则 null |
| tools[].duration_ms | 工具验证/handler/取消检查所在 span 的 monotonic 差值 | 包括失败和取消；不包括随后来源整理与数据库保存 |
| model_call_count | Provider complete/stream 进入时计数，含规划、行动选择、replanning、修复、最终/部分总结和失败尝试 | 精确到应用 Provider 调用，不是 SDK 重试后的 HTTP 请求数 |
| model_calls[].duration_ms | 每个 Provider 调用 span 的经过时间 | 流式 span 含消费者暂停/背压、解析和向前端交付等待，不是纯模型计算时间 |
| model_duration_ms / tool_duration_ms | 对已结束 span 耗时求和 | 与总时长差额包含状态保存、上下文组织和事件交付等，不是独立测量的 CPU 时间 |
| usage | 仅当所有已启动模型调用均收到 Usage 时累加实际输入/输出/总 Token | 任意调用未报告则整体 null；不把已知部分冒充完整用量 |
| cost_usd | 当前 Provider 协议没有可靠统一费用字段 | 始终 null，不按免费模型名称猜 0，也不估算账单 |
| budget_tokens | 原执行循环用于预算控制的计数 | budget_tokens_estimated 表示含未报告调用的估算；取消时可能尚未计入最新 stream Usage，不是费用或 Usage 替代 |
| failure_stage / failure_type | setup、planning、action_selection、replanning、tool_call_repair、final_answer、partial_answer、citation_validation、persistence 等阶段；预算停止标记 budget 与具体原因 | 记录异常类名/受控终止类型，不保存异常正文、Prompt 或文档内容 |

model_calls/tools 保存有限调用的阶段、序号、状态、耗时、异常类，以及模型标识/Usage。恢复成功的工具错误留在工具记录，任务最终成功时 failure_type 仍为 null；终止错误单独标记。

取消可能发生在 Provider 已返回 Usage、但执行器尚未检查取消的边界：已收到的真实 Usage 可以保留；尚未收到的用量必须为 null。任务仍为 cancelled，未完成回答不保存。

## 保存与接口

- 不新增表/列，不执行 PostgreSQL ALTER，不进行旧数据回填。
- 使用既有 agent_runs.plan_json 的可选 JSON envelope：`{"steps": [...], "metrics": {...}}`。没有指标的旧记录仍保留/读取原数组格式。
- update_agent_run 在改计划时保留 metrics，在改 metrics 时保留计划；外部 API 的 plan 仍是数组。get_agent_run 增加可选 metrics，并为现有 Step 投影 duration_ms。
- 新指标存在时，详情顶层 Token 字段与 metrics.usage 对齐；Usage 不完整返回 null。旧记录不推算耗时，前端显示“暂无运行指标”。旧数据库 Token 整数字段保留兼容，新 metrics 是完整性判定依据。
- 沿用 GET /agent-runs/{run_id}、/latest 的 Workspace 过滤。新增 agent_metrics SSE 事件，包含 run_id 与 metrics；前端只接受当前 Run 的数据。
- 初始化、规划后、工具完成/失败、最终完成/失败/取消时保存快照。连接关闭时只保存，不尝试向已关闭的 generator yield。最终快照冻结时长；已经完成保存的任务不会因随后连接关闭被改写为取消。
- 原 AgentRunPanel 增加折叠“运行指标”，展示耗时、调用次数、Usage/未知费用、分步模型与工具耗时、终止阶段和类型；刷新通过原详情接口恢复。

## 数据与部署边界

本轮开发和验收只使用临时 SQLite、Mock Provider 与故障注入，没有连接/修改用户 PostgreSQL，也没有调用 Exa/DeepSeek/OpenRouter。PostgreSQL 独立恢复验收仍阻断，不能据此宣布真实 PostgreSQL 验收完成。

新代码可以读旧数组；旧版本代码不能理解新 envelope。部署时应避免新旧读写代码混用，回滚前需要在隔离副本验证新记录的读取/转换策略；本轮不自动转换原库。任何生产部署和数据变换继续受已有备份/恢复要求约束。

## 局限

- 不是浏览器渲染时间、网络链路追踪或 GPU 计算测量；不提供持续刷新的前端秒表，进行中显示最近事件的快照。
- 总时长包括生成器被消费者暂停的等待；异常类型是到达编排边界的 Python 类型，不保证保留第三方全部原始错误码。
- SDK 内部重试次数/未知计费不可见；工具 Token 与第三方搜索费用不计入 LLM Usage。硬进程退出/数据库不可用时无法保证写入最后快照，取消要等执行器观察到。
- 新 metrics 不保存目标、Prompt、工具参数或结果正文；原系统已有业务消息与步骤预览的存储行为不由本轮扩大。仍需按既有隐私策略管理这些业务数据。
- plan_json 是内部存储形状的小幅扩展，外部 plan 契约不变；不等于新增任务恢复或分布式追踪能力。

## 验证

新增离线用例覆盖：精确模拟单调时钟时长、正常完成、工具失败后继续、规划/决策/流式 LLM 失败、Usage 到达前后两种取消、预算终止、Usage 缺失、格式修复的失败尝试计数、Citation 缓冲与 TTFT、连接关闭、旧计划兼容与更新合并、HTTP SSE/详情/Workspace 一致性。

本轮没有重新进行真实浏览器验收，不能把 TypeScript/build 或 ASGI TestClient 冒充浏览器实测。最终测试数量与 CI 见 CHANGELOG / 对应提交。
