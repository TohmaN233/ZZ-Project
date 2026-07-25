# ZZ Multiplayer VM Deployment

This runbook prepares a Linux VM deployment without assuming access to the
user's VM, DNS provider or certificate account. Replace every
`multiplayer.example.com` placeholder before enabling the service.

## Required Human Inputs

- VM distribution/version and CPU architecture.
- SSH host, user and authentication method.
- Production domain and DNS control.
- Existing reverse proxy, occupied ports and process supervisor.
- TLS certificate/renewal owner.
- Cloud firewall policy and required log retention.

Record the answers in `docs/multiplayer/human-help-checklist.md`. Do not place
SSH keys, passwords, API tokens or certificate private keys in this repository.

## Deployment Shape

```text
Internet :443
    |
Nginx TLS termination
    |-- /multiplayer -> ws://127.0.0.1:32145
    `-- /healthz    -> http://127.0.0.1:32146/healthz
```

Only ports 80/443 should be public. The authoritative WebSocket and health
ports stay bound to loopback; do not expose 32145/32146 in the VM or cloud
firewall.

## Install

The commands below assume a Debian/Ubuntu VM with systemd and Nginx. Adapt the
package-manager commands if the confirmed VM uses another distribution.

```bash
sudo useradd --system --home /opt/zz --shell /usr/sbin/nologin zz
sudo install -d -o zz -g zz /opt/zz
# Place the clean release contents in /opt/zz using the approved upload method.
sudo -u zz python3 -m venv /opt/zz/.venv
sudo -u zz /opt/zz/.venv/bin/pip install --upgrade pip
sudo -u zz /opt/zz/.venv/bin/pip install --no-cache-dir '/opt/zz[multiplayer]'
```

Install configuration only after replacing the domain placeholder:

```bash
sudo install -m 0640 -o root -g zz deploy/zz-multiplayer.env.example /etc/zz-multiplayer.env
sudo install -m 0644 deploy/systemd/zz-multiplayer.service /etc/systemd/system/zz-multiplayer.service
sudo install -m 0644 deploy/nginx/zz-multiplayer.conf /etc/nginx/sites-available/zz-multiplayer.conf
sudo ln -s /etc/nginx/sites-available/zz-multiplayer.conf /etc/nginx/sites-enabled/zz-multiplayer.conf
```

`PUBLIC_ORIGIN` must exactly match the browser Origin, such as
`https://multiplayer.example.com`. `ROOM_IDLE_TIMEOUT_MS` must not be shorter
than `RECONNECT_GRACE_MS`. The example token bucket allows 20 messages per
second per connection with a burst of 40; keep both limits enabled for public
deployment.

Provision TLS through the VM's existing certificate workflow. For a new
Certbot-managed Nginx host, the operator may use:

```bash
sudo certbot --nginx -d multiplayer.example.com
```

Do not run that command until DNS resolves to the VM and the certificate owner
has approved the renewal method.

## Validate And Start

```bash
sudo /opt/zz/.venv/bin/python -m zz.multiplayer.deployment_server --check-config
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now zz-multiplayer
sudo systemctl reload nginx
curl --fail --silent http://127.0.0.1:32146/healthz
curl --fail --silent https://multiplayer.example.com/healthz
sudo systemctl status zz-multiplayer --no-pager
```

The health response contains only `status` and `protocolVersion`. It must not
contain room, match, player, deck, card or reconnect information.

## Logs And Restart

Application logs are one-line structured JSON in the systemd journal. They
contain bounded lifecycle identifiers and error metadata, never hands, deck
order, reconnect tokens, display names, actions or complete snapshots. Nginx records only the HTTP
upgrade/health request metadata, not WebSocket message bodies.

```bash
sudo journalctl -u zz-multiplayer -f
sudo systemctl restart zz-multiplayer
```

The systemd unit uses `Restart=on-failure` and starts after VM reboot. A server
process restart does not restore live matches; clients receive a connection
failure and must create a new room. Persistent server-crash recovery is outside
the first release scope.

## Rollback

Keep the previous clean release directory as an immutable versioned sibling.
To roll back, stop the service, point `/opt/zz` to the previously validated
release using the VM's approved release-switch procedure, run the config and
health checks again, then restart. Never overwrite a live release before a
known-good rollback target exists.

## External Acceptance

After DNS/TLS are ready, two humans on different networks must complete the
Internet section of `human-help-checklist.md`. Automated localhost tests are
not evidence that public routing, certificates or cloud firewall rules work.
