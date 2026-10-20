# 真实 Citation 与 PostgreSQL 备份检查 — 2026-10-20

## 范围与同步

- 工作区开始时干净，在 feat/agent-core 由 04624ed 安全 fast-forward 到 18a356e；读完根目录 AGENTS.md / CHANGELOG.md，沿用低 Token、Mock 优先、提交/Push/PR 留痕规范。
- 首次远程 HEAD 查询发生 TLS 握手失败；随后正常 git fetch 成功，没有修改 TLS 安全设置或强推。
- 本轮只修改验收记录和 CHANGELOG，无运行时代码或 .env 改动，不修改 main。

## 真实免费模型验证：PASS（一次最小最终回答检查）

- 经用户单独确认后，仅执行 1 次真实推理 POST；之前仅执行 1 次公开模型目录 GET： https://openrouter.ai/api/v1/models 。目录 HTTP 200，固定模型存在，输入/输出单价均为 0，声明支持 tools。
- 请求/实际模型均为 nvidia/nemotron-3-super-120b-a12b:free。目录可见与一次推理成功不能推导长期可用性或稳定成功率。
- 复用已存 Exa 结果里的 Qwen-Agent URL，并加入合成知识来源；没有调用 Exa、真实 RAG/Embedding，也未发送私人聊天或用户文档。
- 使用现有 OpenRouterProvider.stream 与 CitationRegistry / CitationStream。只对验收实例关闭 SDK 重试并设置 60 秒超时，没有修改生产 Provider 默认行为。失败不会重试、充值或切换模型。
- 预算：输入最多 2,000 Token、输出 max_tokens=256；请求文本 1,240 UTF-8 字节，模板保守预留 256，输入预检 1,496。实际 prompt_tokens=365、completion_tokens=209、total_tokens=574。
- 流式收到 12 个模型文本增量；首段可见文字 4.312 秒，总耗时 6.219 秒。API usage 报告 cost=0 美元。
- 来源 1 为合成 knowledge；来源 2 为真实搜索记录里的 Qwen-Agent Web URL。重复加入同一 URL 后仍是两个来源。
- 模型按目录复制 marker，服务端转换后的正文：

```text
Qwen-Agent 【2】
Local test evidence 【1】
```

Qwen-Agent 对应 URL： https://github.com/QwenLM/Qwen-Agent/blob/31a4d36d/README_CN.md 。

- 断言通过：正文引用集合仅为 1/2；Qwen URL 对应 source 2；重复 URL 去重；无内部 marker 泄露；逐增量与一次性转换完全相同；实际 Token 未超过批准上限。
- 该检查验证真实模型最终回答对现有 Citation 协议的一次遵循，不是新一轮完整 Agent 规划/多工具/HTTP/浏览器真实 Provider 联调。先前 HTTP 和浏览器证据仍是回放结果。

## PostgreSQL：备份检查通过，恢复/迁移验收 BLOCKED

- 直接使用只读 psycopg 连接，未调用会自动初始化 Schema 的应用连接入口。
- 实际数据库 sources_json 已存在：TEXT NOT NULL DEFAULT '[]'::text。不能再称该列尚未创建，也不能据此推断既往迁移过程正确。
- 只读快照计数：chat_messages=146、chat_sessions=57、workspaces=2。
- PostgreSQL 17 pg_dump 使用导出的一致性快照生成 custom 格式备份；pg_restore --list 成功，可解析归档。归档大小 76,584 字节，SHA-256 为 7c96f5888d8d655d4380b41c0da2568fa5d3d35ede20da4719fe3241a6d4492a。
- 备份留在仓库外：%TEMP%/paw-citation-pg-20261020/paw_citation_verify_f33ad14a0e31.dump。备份含原始业务数据，不加入 Git，也未上传 GitHub。
- 下一步创建隔离恢复库时返回 InsufficientPrivilege。只读确认当前账号 rolcreatedb=false，目标副本不存在；立即停止所有数据库写入验证，没有尝试提升权限、改用管理员账号或改写生产数据。
- 后续只读计数仍为 146/57/2。原库没有执行 ALTER、UPDATE、DELETE 或应用保存，也没有删除已有数据。
- 归档目录可读不等同于完整恢复成功；备份完整恢复、旧表缺列迁移、现有列幂等性、PostgreSQL 应用 Sources 保存/读取仍未通过本轮实测。
- 建议管理员预建独立验收数据库并授予验收账号仅该库内必要权限；随后恢复备份，对副本执行迁移及 Sources 回读，并比对消息、来源、Workspace 指纹。无需授予应用账号全局 CREATEDB，不修改用户原库。

## 测试、费用与遗留

- 针对性离线回归：Citation + Persistence，19 passed、59 subtests passed，4.77 秒；1 条现有 Starlette/anyio 弃用警告。
- 本轮无代码修改，按 AGENTS.md 不重复执行本地完整后端/前端构建；此前完整回归 136 passed、65 subtests passed，类型检查/构建/CI 通过是历史结果，不冒充本轮重跑。
- 实际新增：模型目录 GET 1、推理 POST 1；Exa 0、Embedding 0；模型 API 报告费用 $0。不读取账户账单，不保证历史测试隔离缺口造成的未知消耗为 0。
- 敏感信息检查只扫描本轮两份文档和 staged diff，备份、凭据、数据库及临时脚本不提交。
- 阻断：真实 PostgreSQL 恢复/迁移仍未验收；不能宣称最后两项全部完成。
