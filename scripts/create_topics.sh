#!/usr/bin/env bash
set -euo pipefail

BROKERS="${BROKERS:-127.0.0.1:19092}"

if [[ -z "${REDPANDA_CONTAINER:-}" ]]; then
  for candidate in web-osint-redpanda x-research-redpanda; do
    if docker inspect "$candidate" >/dev/null 2>&1; then
      REDPANDA_CONTAINER="$candidate"
      break
    fi
  done
fi

if [[ -z "${REDPANDA_CONTAINER:-}" ]]; then
  echo "Could not find a Redpanda container. Set REDPANDA_CONTAINER explicitly." >&2
  exit 1
fi

RPK=(docker exec "$REDPANDA_CONTAINER" rpk topic)

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
create_topic evidence.web.documents.observed.v1 delete
create_topic evidence.user.inputs.observed.v1 delete
create_topic evidence.capture.shadow.validated.v1 delete
create_topic evidence.capture.shadow.errors.v1 delete
create_topic evidence.capture.shadow.observed.v1 delete
create_topic osint.semantic.segmented.v1 delete
create_topic osint.semantic.embedded.v1 delete
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
create_topic osint.media.enrichment.requested.v1 delete
create_topic osint.media.ocr.requested.v1 delete
create_topic osint.media.ocr.completed.v1 delete
create_topic osint.media.ocr.failed.v1 delete
create_topic osint.media.vl_embedding.requested.v1 delete
create_topic osint.media.vl_embedding.completed.v1 delete
create_topic osint.media.vl_embedding.failed.v1 delete

create_topic evidence.posts.state.v1 compact
create_topic evidence.accounts.state.v1 compact
create_topic evidence.media.state.v1 compact
create_topic evidence.web.documents.state.v1 compact
create_topic evidence.user.inputs.state.v1 compact
create_topic osint.state.current_labels_by_target.v1 compact
create_topic osint.state.entity_by_alias.v1 compact
create_topic osint.state.entity_current.v1 compact
create_topic osint.state.claim_current.v1 compact
create_topic osint.state.open_tasks_by_dedupe_key.v1 compact
create_topic osint.state.wiki_page_current.v1 compact
create_topic evidence.index.errors.v1 delete

echo "Topic bootstrap complete"
