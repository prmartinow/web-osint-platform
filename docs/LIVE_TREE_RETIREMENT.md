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

## Current State (2026-07-05)

The canonical-stack cutover (REPO-01) is verified Done. All compose-managed
services run against the canonical `docker-compose.yml` (bare service names),
all persistent data survived via bind mounts, and a fresh capture flowed
end-to-end into the Source Library.

### Remaining retirement steps (the REPO-04 deletion)

The running containers still carry launch-context labels pointing at the legacy
live tree (the recreate commands were issued from there), and the complete
deployment `.env` lives at the legacy root, not yet at the canonical root.
Retiring the legacy tree therefore requires, in order:

1. Copy the complete legacy deployment `.env` to the canonical repo root (it is
   gitignored there) so the canonical tree is self-sufficient.
2. Re-launch the compose stack **from the canonical repo's compose directory**
   (`cd $WEB_OSINT_REPO_ROOT/compose && docker compose -p $WEB_OSINT_COMPOSE_PROJECT --env-file ../.env up -d --force-recreate`), so the running containers
   get canonical-path launch labels. Durable data is unaffected (bind mounts
   point at WEB_OSINT_DATA_ROOT, not the source tree).
3. Verify the stack is healthy post-relaunch (research-ui, dashboard, the data
   stores, and a fresh capture through to the Library).
4. With operator approval, remove the legacy live tree. Per the decision above,
   this is a replace (no archive, no symlink/worktree wrapper).

### Blocker

Step 4 (the actual `rm -rf` of the legacy tree) needs explicit operator
approval at the moment of action, since the legacy tree was the live deployment
for a long time. Steps 1-3 are reversible and can proceed first.
