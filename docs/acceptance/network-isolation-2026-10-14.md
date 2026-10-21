# 网络隔离自检修复 — 2026-10-14

## 最终结果

- 隔离自检：`10 passed`。
- 后端完整测试：`134 passed, 62 subtests passed`，耗时 14.85 秒。
- `git diff --check` 通过；有现有 CRLF 提示和 1 条 Starlette/anyio 弃用警告。
- 保留原失败测试和全部断言；本轮业务代码未改动。
- 分支仍为 `feat/agent-core`，HEAD 仍为 `f14e83e`；未提交、未推送、未修改 main。
- 未调用真实 Exa、DeepSeek 或 OpenRouter，未使用真实 API Key 发起请求。

## 原失败与 traceback

测试为 `test_stdlib_dns_sockets_udp_and_native_ddgs_are_blocked`。
上轮失败断言位于 `backend/app/tests/test_network_isolation.py:44`：

```text
    with pytest.raises(NetworkBlocked):
E   Failed: DID NOT RAISE NetworkBlocked
app\tests\test_network_isolation.py:44
```

该循环顺序为 DNS、urllib、DDGS。原 traceback 没有记录具体 lambda，单凭 traceback 无法区分失败操作。

本轮首次只修正 DDGS 后，综合测试仍在相同断言失败；新增回归导致行号变为 54：

```text
___________ test_stdlib_dns_sockets_udp_and_native_ddgs_are_blocked ___________
    for operation in (
        lambda: socket.getaddrinfo("api.exa.ai", 443),
        lambda: urllib.request.urlopen("https://example.com", timeout=1),
        lambda: DDGS(timeout=1),
    ):
>       with pytest.raises(NetworkBlocked):
E       Failed: DID NOT RAISE NetworkBlocked
app\tests\test_network_isolation.py:54
1 failed, 6 passed
```

后续静态分析及无真实 I/O 的受控复现确认：当前环境中首先失败的是 urllib 的本地代理路径，DDGS 另有独立的 patch 缺口。最初将 DDGS 视为唯一失败点的判断不完整，已在本轮报告中更正。

## 根因一：urllib 经回环代理绕过 Socket 检查

当前进程配置了回环 HTTP 代理。调用链为：

`urllib.request.urlopen(外部 HTTPS URL)` → `ProxyHandler` → `HTTPSConnection` → 本地代理连接 → HTTPS CONNECT 外部目标。

原 guard 只在 DNS/Socket 层检查目标主机。此处 Socket 连接的是回环代理，因此被允许；没有检查代理所转发的外部目标。这是真实的未拦截路径，不是异常类型或测试断言错误。

安全复现使用 `127.0.0.1:9` 作为不可实际连接的代理，并将底层 Socket 连接替换为立即抛错的哨兵。结果：guard 尝试计数 0，底层哨兵阻止连接 1 次，证明请求越过了原 guard，但没有建立真实连接。

修复：在测试 guard 中 patch `http.client.HTTPConnection.putrequest`，发送前检查绝对 URL 的主机、HTTPS `_tunnel_host` 或连接主机。外部目标抛出同一 `NetworkBlocked`；真正的回环请求继续允许。

## 根因二：DDGS patch 了懒加载代理的构造函数

本机 DDGS 版本为 9.16.0。`from ddgs import DDGS` 导出 `_DDGSProxy`；其元类 `_ProxyMeta.__call__` 调用 `_load_real()` 后直接构造 `ddgs.ddgs.DDGS`，绕过代理自身的 `__init__`。

原 guard patch 代理 `__init__`，真实实现的构造函数未被拦截。真实构造函数仅设置成员，所以 `DDGS(timeout=1)` 可以正常返回。单独构造并不代表已发送搜索请求；但后续 `.text()` 可进入原生网络客户端，因而这是实际隔离缺口。

安全复现先将真实构造函数替换为仅计数的无副作用函数，并在 DNS/Socket 层设置哨兵。六条路径中五条抛出 `NetworkBlocked`，只有 DDGS 正常返回；无副作用构造函数调用 1 次，底层网络哨兵触发 0 次。

修复：conftest 改为 `from ddgs.ddgs import DDGS`，patch 真实实现的 `__init__`。已提前绑定的公共代理别名和直接实现类均会进入同一个受保护构造函数，消除该导入顺序问题。

## fixture、monkeypatch 与异常检查

- `backend/conftest.py` 的 autouse fixture 覆盖 backend 下当前常规 pytest 用例；每个测试执行前安装 guard，并清空运行时 Provider 凭据。
- 内层 `monkeypatch.context()` 的 guard 计数与外层 fixture 独立；内层负向自检不会污染外层的意外网络计数。context 退出后恢复外层 guard。
- `NetworkBlocked` 继承 `AssertionError`。标准库通常捕获 `OSError` 包装为 `URLError`，不会把这里的 `NetworkBlocked` 吞掉；安全复现也验证了该异常类型直接到达断言。
- HTTPX 同步/异步默认 transport 均被 patch；MockTransport 和 TestClient 的 ASGI transport 不经过默认 transport，继续可用。
- 原综合测试增加底层连接哨兵，即使未来 guard 回归，也不会通过回环代理建立真实连接。
- 新增 HTTP/HTTPS 代理自检在 `socket.create_connection` 放置哨兵，验证目标检查在网络 I/O 之前完成。

## 已验证与未验证

| 路径 | 本轮证据 | 状态 |
| --- | --- | --- |
| HTTPX 同步：Exa/DeepSeek/OpenRouter URL | 三个默认 transport 拦截用例 | 已验证；没有发送请求 |
| HTTPX 异步 | 默认异步 transport 拦截用例 | 已验证；没有发送请求 |
| DNS `getaddrinfo` 外部主机 | 原综合测试 | 已验证 |
| TCP `connect` / `connect_ex` 外部 IP | 原综合测试 | 已验证 |
| UDP `sendto` 外部 IP | 原综合测试 | 已验证 |
| urllib 经回环代理访问外部 HTTP / HTTPS | 两个代理回归，底层 I/O 哨兵 | 已验证 |
| DDGS 公共代理别名 / 真实实现构造 | 两个构造回归 | 已验证；构造即被阻止 |
| HTTPX MockTransport、回环 DNS、ASGI 本地测试 | 保留的兼容用例和完整测试 | 已验证 |
| 已在 fixture 前创建的 DDGS 实例、其他原生 C/Rust 网络库 | 未运行 | 未验证 |
| 其他 DNS API、已有连接的 send/sendall、任意自定义代理隧道 | 未运行 | 未验证 |
| pytest collection/import 阶段的通用网络阻断 | fixture 在测试执行前安装，不覆盖所有导入 | 未验证；不能宣称进程级或 OS 级断网 |
| 真实 Provider、账单、免费额度、真实模型引用协议 | 本轮未运行 | 未验证 |
| 前端构建、浏览器、六场景实际 HTTP 回放 | 本轮只改测试设施，未重跑 | 本轮未验证；见上轮独立报告 |

修复后受额外底层哨兵保护的五项针对性检查全部通过，哨兵触发 0 次；随后完整隔离自检 10 项和后端 134 项全部通过。

## 操作偏差说明

最初安全复现为了确保不连外网，显式禁用了 urllib 代理，因此暴露了 DDGS 缺口，却掩盖了本机代理绕过。只修 DDGS 后运行普通隔离自检时，urllib 可能通过本机代理访问了 `example.com`。没有保留响应详情，不能声称该次运行外部请求为 0；未调用 Exa/LLM 服务。发现第二次失败后，停止后续全套测试，先以底层连接哨兵证明代理路径，再完成修复和重跑。

## 本轮改动文件

- `backend/conftest.py`：真实 DDGS 构造函数 patch、标准库 HTTP 逻辑目标检查。
- `backend/app/tests/test_network_isolation.py`：保留综合断言并加安全哨兵；新增 DDGS 两种构造路径及 HTTP/HTTPS 代理回归。
- 本报告：`docs/acceptance/network-isolation-2026-10-14.md`。

其余未提交 Citation 改动保留。本轮没有创建提交或推送。
