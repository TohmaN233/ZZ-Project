# ZZ 联机网络检测

此工具检查当前设备到指定 ZZ 服务器的连接链路。无需账号、卡图、AI 模型或其他玩家，不创建房间，也不操作任何现有对局。它不会上传日志。

## Windows 一键运行

解压对应版本的 `ZZ-Network-Diagnostic-v<版本>-Windows.zip`，双击 `Start-Diagnostic.cmd`，等待约 60 秒。保留同目录下新生成的 `zz-multiplayer-network-diagnostic-*.json`。

先关闭代理，采集直连报告，并注明网络运营商。如果使用 VPN/TUN，可以再开启后运行一次作对照；仅有 HTTP 系统代理时，应通过游戏客户端自身的连接日志验证代理路线。无需提供代理地址、账号或订阅。

工具明确绕过应用层和系统 HTTP 代理。开启仅有 HTTP 系统代理的客户端，不会改变这个工具的路线；VPN/TUN/透明转发仍可能改变出口。它不能自行证明请求来自大陆，也不能把加拿大测试结果当成大陆直连结果。客户端本身的自动代理选择仍由游戏处理。

## 检测范围和结果

| 阶段 | 检查内容 | 失败时的含义 |
| --- | --- | --- |
| DNS | 使用设备的系统解析器获取地址 | 解析失败或超时 |
| TCP | 尝试解析到的地址及目标端口 | 端口不可达、拒绝或连接超时 |
| TLS | 在选中的 TCP 连接上验证证书和主机名 | 握手失败、证书错误或超时 |
| WebSocket | 在同一条连接上完成 Upgrade | 服务端拒绝升级或连接中断 |
| 游戏 HELLO | 使用包内版本清单，要求返回匹配的 WELCOME | 版本不兼容、游戏协议错误或超时 |
| 心跳 | 保持连接并等待每次 ping 的 pong | 断线、心跳超时；报告包含 RTT 样本及统计 |
| 独立健康检查 | 另行访问健康域名并验证 JSON | 辅助证据，不能替代游戏域名的检测 |

成功表示这条连接在本次观察窗口内通过。它不是并发压测，也不等于完成一整场对局。失败报告保留具体阶段及错误类型，命令返回非零退出码；请不要只根据一个 HTTP 状态或平均延迟判断问题。

默认目标为 `wss://zz.tgy233.top/multiplayer`；健康检查为 `https://zz-health.tgy233.top/healthz`。后者是独立域名。对游戏地址发普通 HTTPS GET 得到 426 可以是预期行为，不能据此判定 WebSocket 失败。

JSON 仅保留目标地址、解析结果、阶段耗时、错误代码、版本和心跳统计等诊断证据；不记录本机用户名、设备名、代理地址、房间凭据或原始游戏消息。

## 源码运行或自动化

源码包只需要 Python 3.10+ 和 `requirements.txt` 中的 `websockets`，无需完整游戏：

```bash
python -m pip install -r requirements.txt
python multiplayer_network_diagnostic.py --duration 60 --output direct.json
```

在项目根目录也可以运行：

```bash
python -m tools.multiplayer_network_diagnostic --duration 60 --output direct.json
```

增加观察时间：

```bash
python multiplayer_network_diagnostic.py --duration 1800 --interval 5 --output long-run.json
```

使用 `--help` 查看目标、超时和清单参数。版本清单必须对应实际测试的客户端；服务端升级后，应重新构建检测包或显式指定对应的 `--manifest`。不要为让检测通过而采用服务端返回的版本替换预期版本。

## 无需大陆玩家的初筛

可使用 ITDOG 的运营商 DNS 和三网节点运行一次 TCP/HTTPS 检查：

- TCP：`zz.tgy233.top:443`。
- HTTPS：`https://zz.tgy233.top/multiplayer`，普通 GET 预期是 426。
- 健康检查：`https://zz-health.tgy233.top/healthz`，预期 200。

保存当时的节点明细和时间；公开探针结果可能变化，不能只保存可重新发起测试的网址。探针的 TCP 成功仅能证明端口可达，HTTP 成功仅能证明对应请求收到响应。公开工具不执行游戏 HELLO 和持续心跳时，这两项必须保持未验证。

如有大陆远程主机，可以在其上运行源码包，补充真正的 WSS/HELLO 证据；云机线路仍不代表所有家庭宽带。最后用大陆玩家的真实设备完成直连、进房、对局和断网恢复验收。

## 构建检测包

已安装 PyInstaller 的 Windows 开发环境中运行，输出目录必须不存在：

```powershell
python packaging/build_network_diagnostic.py --output-dir D:\ZZ-Network-Package
```

输出包含 Windows ZIP、独立源码 ZIP 和 ZIP 的 SHA-256 清单。构建缓存位于自动清理的临时目录，包内不包含测试报告、源码树、游戏资源或构建缓存。
