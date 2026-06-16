#!/usr/bin/env bash
set -Eeuo pipefail

DATA_ROOT="${WEB_OSINT_DATA_ROOT:-/mnt/data/web-osint-platform}"
MODELS_DIR="${WEB_OSINT_MODELS_DIR:-$DATA_ROOT/models}"
LOG_DIR="${WEB_OSINT_MODEL_LOG_DIR:-$DATA_ROOT/logs/model-downloads}"
INTERVAL="${WEB_OSINT_DOWNLOAD_PROGRESS_INTERVAL:-15}"
DOWNLOAD_SERVICE="${WEB_OSINT_DOWNLOAD_SERVICE:-web-osint-qwen-model-downloads.service}"

mkdir -p "$LOG_DIR"
PROGRESS_LOG="$LOG_DIR/qwen-model-download-progress-$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sfn "$PROGRESS_LOG" "$LOG_DIR/latest-progress.log"

human_bytes() {
  awk -v bytes="${1:-0}" 'BEGIN {
    sign = "";
    if (bytes < 0) {
      sign = "-";
      bytes = -bytes;
    }
    split("B KiB MiB GiB TiB", units, " ");
    unit = 1;
    while (bytes >= 1024 && unit < 5) {
      bytes = bytes / 1024;
      unit++;
    }
    printf "%s%.2f%s", sign, bytes, units[unit];
  }'
}

human_rate() {
  printf "%s/s" "$(human_bytes "${1:-0}")"
}

duration() {
  local seconds="${1:-0}"
  if (( seconds < 0 )); then
    seconds=0
  fi
  printf "%02d:%02d:%02d" "$((seconds / 3600))" "$(((seconds % 3600) / 60))" "$((seconds % 60))"
}

dir_bytes() {
  local path="$1"
  if [[ -d "$path" ]]; then
    du -sb "$path" 2>/dev/null | awk '{print $1}'
  else
    printf "0"
  fi
}

active_model() {
  pgrep -af "hf download Qwen/" 2>/dev/null \
    | sed -E 's/.*hf download (Qwen\/[^ ]+).*/\1/' \
    | head -1
}

download_pid() {
  pgrep -f "hf download Qwen/" 2>/dev/null | head -1
}

service_elapsed_seconds() {
  local active_ts
  active_ts="$(systemctl --user show "$DOWNLOAD_SERVICE" -p ActiveEnterTimestamp --value 2>/dev/null || true)"
  if [[ -z "$active_ts" || "$active_ts" == "n/a" ]]; then
    printf "0"
    return
  fi

  local active_epoch now_epoch
  active_epoch="$(date -d "$active_ts" +%s 2>/dev/null || printf "0")"
  now_epoch="$(date +%s)"
  if [[ "$active_epoch" =~ ^[0-9]+$ && "$active_epoch" -gt 0 ]]; then
    printf "%s" "$((now_epoch - active_epoch))"
  else
    printf "0"
  fi
}

model_summary() {
  local items=()
  local dir
  shopt -s nullglob
  for dir in "$MODELS_DIR"/*; do
    [[ -d "$dir" ]] || continue
    items+=("$(basename "$dir")=$(human_bytes "$(dir_bytes "$dir")")")
  done
  shopt -u nullglob
  if (( ${#items[@]} == 0 )); then
    printf "none"
  else
    local IFS=","
    printf "%s" "${items[*]}"
  fi
}

incomplete_count() {
  find "$MODELS_DIR" -name "*.incomplete" -type f 2>/dev/null | wc -l | tr -d " "
}

incomplete_total_bytes() {
  find "$MODELS_DIR" -name "*.incomplete" -type f -printf "%s\n" 2>/dev/null \
    | awk '{sum += $1} END {printf "%.0f", sum + 0}'
}

incomplete_top_sizes() {
  local sizes
  sizes="$(
    find "$MODELS_DIR" -name "*.incomplete" -type f -printf "%s\n" 2>/dev/null \
      | sort -nr \
      | head -4
  )"
  if [[ -z "$sizes" ]]; then
    printf "none"
    return
  fi

  local items=()
  while read -r size; do
    [[ -n "${size:-}" ]] || continue
    items+=("$(human_bytes "$size")")
  done <<< "$sizes"

  local IFS=","
  printf "%s" "${items[*]}"
}

log_progress() {
  local now now_epoch state total delta elapsed interval_rate avg_rate svc_elapsed model pid sockets
  now="$(date -Is)"
  now_epoch="$(date +%s)"
  state="$(systemctl --user is-active "$DOWNLOAD_SERVICE" 2>/dev/null || true)"
  total="$(dir_bytes "$MODELS_DIR")"
  delta="$((total - LAST_TOTAL_BYTES))"
  elapsed="$((now_epoch - LAST_EPOCH))"
  if (( elapsed > 0 )); then
    interval_rate="$((delta / elapsed))"
  else
    interval_rate=0
  fi
  local monitor_elapsed="$((now_epoch - START_EPOCH))"
  if (( monitor_elapsed > 0 )); then
    avg_rate="$(((total - START_TOTAL_BYTES) / monitor_elapsed))"
  else
    avg_rate=0
  fi
  svc_elapsed="$(service_elapsed_seconds)"
  model="$(active_model || true)"
  if [[ -z "$model" ]]; then
    model="none"
  fi
  pid="$(download_pid || true)"
  if [[ -n "$pid" ]]; then
    sockets="$(ss -tpn 2>/dev/null | grep -F "pid=$pid," | wc -l | tr -d " ")"
  else
    sockets=0
  fi

  printf "[%s] state=%s active_model=%s service_elapsed=%s monitor_elapsed=%s total=%s window_delta=%s window_rate=%s avg_rate=%s sockets=%s models=%s incomplete_count=%s incomplete_total=%s incomplete_top=%s\n" \
    "$now" \
    "$state" \
    "$model" \
    "$(duration "$svc_elapsed")" \
    "$(duration "$monitor_elapsed")" \
    "$(human_bytes "$total")" \
    "$(human_bytes "$delta")" \
    "$(human_rate "$interval_rate")" \
    "$(human_rate "$avg_rate")" \
    "$sockets" \
    "$(model_summary)" \
    "$(incomplete_count)" \
    "$(human_bytes "$(incomplete_total_bytes)")" \
    "$(incomplete_top_sizes)" \
    | tee -a "$PROGRESS_LOG"

  LAST_TOTAL_BYTES="$total"
  LAST_EPOCH="$now_epoch"
}

START_EPOCH="$(date +%s)"
START_TOTAL_BYTES="$(dir_bytes "$MODELS_DIR")"
LAST_EPOCH="$START_EPOCH"
LAST_TOTAL_BYTES="$START_TOTAL_BYTES"

echo "[$(date -Is)] Web OSINT Qwen model download progress monitor starting interval=${INTERVAL}s" | tee -a "$PROGRESS_LOG"
log_progress

while true; do
  sleep "$INTERVAL"
  log_progress
done
