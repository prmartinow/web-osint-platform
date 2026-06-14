#!/usr/bin/env bash
set -euo pipefail

BROKERS="${BROKERS:-127.0.0.1:19092}"
RPK=(docker exec web-osint-redpanda rpk topic)

create_topic() {
  local topic="$1"
  local cleanup="$2"
  if "${RPK[@]}" describe "$topic" --brokers "$BROKERS" >/dev/null 2>&1; then
    echo "Topic exists: $topic"
  else
    "${RPK[@]}" create "$topic" --brokers "$BROKERS" -p 1 -r 1 -c "cleanup.policy=$cleanup"
    echo "Created topic: $topic"
  fi
}

create_topic evidence.capture.events.v1 delete
create_topic evidence.posts.observed.v1 delete
create_topic evidence.accounts.observed.v1 delete
create_topic evidence.media.observed.v1 delete
create_topic evidence.search.results.v1 delete

create_topic evidence.posts.state.v1 compact
create_topic evidence.accounts.state.v1 compact
create_topic evidence.media.state.v1 compact
create_topic evidence.index.errors.v1 delete

echo "Topic bootstrap complete"

