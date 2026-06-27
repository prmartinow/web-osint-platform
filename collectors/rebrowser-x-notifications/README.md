# Rebrowser X Notifications Collector

Collects a small, human-paced X notifications sample from the preserved
Rebrowser profile and publishes it as a normal Web OSINT capture event.

Run from the machine that has access to the preserved Rebrowser CDP session.
Keep endpoint, SSH, data-root, and account values in local env or an ignored env
file:

- `REBROWSER_CDP_URL`
- `REBROWSER_X_HELPERS`
- `WEB_OSINT_RPC_SSH_HOST`
- `WEB_OSINT_RPC_SSH_PORT`
- `WEB_OSINT_RPC_DATA_ROOT`
- `WEB_OSINT_REMOTE_PANDAPROXY_URL`
- `WEB_OSINT_X_EXPECTED_ACCOUNT`

```bash
node collectors/rebrowser-x-notifications/x_notifications_capture.mjs \
  --source-project x-notifications \
  --publish
```

The collector:

- connects to the env-configured Rebrowser CDP endpoint;
- opens a task-owned tab at `https://x.com/notifications`;
- follows the slow X helper for dwell, click, and scroll behavior;
- optionally opens the first grouped "New post notifications" row;
- captures visible notifications, posts, account handles, links, and screenshots;
- uploads artifacts under the env-configured Web OSINT data root;
- publishes one event to `evidence.capture.events.v1` through the env-configured
  RPC-local Pandaproxy endpoint;
- closes only the task-owned tab unless `--keep-tab` is passed.

Stop immediately if the script reports a challenge, 403, 429, CAPTCHA, or
similar X restriction signal.
