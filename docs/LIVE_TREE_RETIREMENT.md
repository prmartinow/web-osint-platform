# Live Tree Retirement

## Decision

Web OSINT uses direct canonical-checkout deployment.

The canonical source tree is `WEB_OSINT_REPO_ROOT`, pointing at the
`prmartinow/web-osint-platform` checkout. The legacy live tree, if present at
`WEB_OSINT_LEGACY_LIVE_ROOT`, is a migration artifact only. It must not receive
new source edits, committed code, generated data, secrets, or model assets.

## Cutover Rules

- Services should start code from `WEB_OSINT_REPO_ROOT`.
- Durable state should stay under `WEB_OSINT_DATA_ROOT` or another explicit
  external data root.
- Local endpoints, credentials, bind hosts, ports, and helper URLs should come
  from ignored env files or secret managers.
- Model serving, downloads, caches, ownership, and maintenance stay in the
  local-inference layer and outside Web OSINT.
- The legacy live tree should be treated as read-only quarantine until all
  source deltas are either migrated into this repository or explicitly dropped.

## Retirement Checklist

1. Set `WEB_OSINT_REPO_ROOT` to the canonical checkout.
2. Set `WEB_OSINT_LEGACY_LIVE_ROOT` only in local ignored env when a legacy tree
   still exists.
3. Confirm every service unit, compose invocation, and operator script starts
   from `WEB_OSINT_REPO_ROOT`.
4. Confirm no service `ExecStart`, working directory, venv path, or helper path
   points inside `WEB_OSINT_LEGACY_LIVE_ROOT`.
5. Confirm all durable data paths point outside the source checkout.
6. Archive or remove the legacy tree only after the above checks pass and the
   operator explicitly approves the local filesystem action.

## Done State

After retirement, the only editable Web OSINT source tree is the canonical
checkout. Any remaining live deployment directory is either absent, a read-only
archive, or a deployment wrapper that points back to `WEB_OSINT_REPO_ROOT`.
