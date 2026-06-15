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
create_topic osint.semantic.segmented.v1 delete
create_topic osint.label.proposed.v1 delete
create_topic osint.label.feedback.v1 delete
create_topic osint.label.resolved.v1 delete
create_topic osint.entity.mentioned.v1 delete
create_topic osint.entity.resolved.v1 delete
create_topic osint.claim.extracted.v1 delete
create_topic osint.relation.extracted.v1 delete
create_topic osint.benchmark_fact.extracted.v1 delete
create_topic osint.release_signal.detected.v1 delete
create_topic osint.research_signal.detected.v1 delete
create_topic osint.research_question.proposed.v1 delete
create_topic osint.research_task.created.v1 delete
create_topic osint.wiki.page_materialized.v1 delete
create_topic osint.semantic.deadletter.v1 delete

create_topic evidence.posts.state.v1 compact
create_topic evidence.accounts.state.v1 compact
create_topic evidence.media.state.v1 compact
create_topic osint.state.current_labels_by_target.v1 compact
create_topic osint.state.entity_by_alias.v1 compact
create_topic osint.state.entity_current.v1 compact
create_topic osint.state.claim_current.v1 compact
create_topic osint.state.open_tasks_by_dedupe_key.v1 compact
create_topic osint.state.wiki_page_current.v1 compact
create_topic evidence.index.errors.v1 delete

echo "Topic bootstrap complete"
