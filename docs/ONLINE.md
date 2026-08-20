# Online Game

## 局域网模式

1. 双方使用同一版本的客户端与资源包。
2. 房主进入 Online Game，切换到 LAN，并启动本地房间。
3. Windows 防火墙第一次询问时，允许游戏访问专用网络。
4. 加入方输入房主界面显示的地址。
5. 创建或加入房间，双方准备后开始对战。

LAN 不需要单独的服务器包。

## 公网模式

客户端默认连接项目维护者的个人服务器（加拿大）。这是个人维护的服务，不承诺持续在线。中国大陆通常需要代理。

双方必须使用同一应用版本、同一协议版本和同一规则 checksum。版本不兼容时先更新客户端。

## 自建服务器

Release 只保留**最新一份**服务器包：

[`ZZ-Multiplayer-v0.3.2-f7a50d6.tar.gz`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.2/ZZ-Multiplayer-v0.3.2-f7a50d6.tar.gz)

SHA-256: `04139BDC15FC9CD65A2F2B0D4F07B008161A8C94493B9F9B1DCB908145EED9CD`

需要 Linux、Python 3.10+，以及一个带 TLS 的 HTTPS 域名。游戏客户端按 `PUBLIC_ORIGIN` 校验来源，所以公网入口必须是 `https://你的域名`，不能带路径。

```bash
mkdir zz-multiplayer
tar -xzf ZZ-Multiplayer-v0.3.2-f7a50d6.tar.gz -C zz-multiplayer
cd zz-multiplayer
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install --no-cache-dir '.[multiplayer]'
cp deploy/zz-multiplayer.env.example zz-multiplayer.env
```

编辑 `zz-multiplayer.env`，至少改这两项：

```text
PUBLIC_ORIGIN=https://your.example.com
PROTOCOL_VERSION=2
```

其余可先保持示例值。`MAX_MESSAGE_BYTES` 需要是 `262144`。不要把填好的 env 提交到 git。

```bash
set -a
source zz-multiplayer.env
set +a
.venv/bin/python -m zz.multiplayer.deployment_server --check-config
.venv/bin/python -m zz.multiplayer.deployment_server
```

进程默认只听本机 `127.0.0.1:32145`（对局 WebSocket）和 `127.0.0.1:32146`（`/healthz`）。前面再放一层 Nginx / Caddy：

- `https://your.example.com/` → `ws://127.0.0.1:32145/`
- `https://your.example.com/healthz` → `http://127.0.0.1:32146/healthz`

`deploy/nginx/zz-multiplayer.conf` 和 `deploy/systemd/zz-multiplayer.service` 是可选模板。先确认：

```bash
curl --fail https://your.example.com/healthz
```

应返回带 `protocolVersion: 2` 的 JSON。然后在客户端 Online Game 里填写 `wss://your.example.com/`。

玩家仍使用普通 Windows / Linux 客户端，不必下载这份服务器包。
