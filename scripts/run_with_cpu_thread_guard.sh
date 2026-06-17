#!/usr/bin/env bash
set -Eeuo pipefail

is_uint() {
  [[ "${1:-}" =~ ^[0-9]+$ ]]
}

detected_total="${WEB_OSINT_CPU_TOTAL_THREADS:-}"
if ! is_uint "$detected_total" || [[ "$detected_total" -lt 1 ]]; then
  detected_total="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
fi
if ! is_uint "$detected_total" || [[ "$detected_total" -lt 1 ]]; then
  detected_total=1
fi

reserved="${WEB_OSINT_CPU_RESERVED_THREADS:-2}"
if ! is_uint "$reserved"; then
  reserved=2
fi
if [[ "$reserved" -ge "$detected_total" ]]; then
  reserved=$((detected_total > 1 ? detected_total - 1 : 0))
fi

effective=$((detected_total - reserved))
if [[ "$effective" -lt 1 ]]; then
  effective=1
fi

clamp_thread_var() {
  local name="$1"
  local fallback="$2"
  local raw="${!name:-$fallback}"

  if ! is_uint "$raw" || [[ "$raw" -lt 1 ]]; then
    raw="$fallback"
  fi
  if [[ "$raw" -gt "$effective" ]]; then
    raw="$effective"
  fi
  export "$name=$raw"
}

export WEB_OSINT_CPU_TOTAL_THREADS="$detected_total"
export WEB_OSINT_CPU_RESERVED_THREADS="$reserved"
export WEB_OSINT_CPU_EFFECTIVE_THREADS="$effective"

clamp_thread_var QWEN_INFERENCE_TORCH_THREADS "${QWEN_INFERENCE_TORCH_THREADS:-$effective}"
clamp_thread_var OMP_NUM_THREADS "${OMP_NUM_THREADS:-$effective}"
clamp_thread_var MKL_NUM_THREADS "${MKL_NUM_THREADS:-$effective}"
clamp_thread_var OPENBLAS_NUM_THREADS "${OPENBLAS_NUM_THREADS:-$effective}"
clamp_thread_var NUMEXPR_NUM_THREADS "${NUMEXPR_NUM_THREADS:-$effective}"
clamp_thread_var BLIS_NUM_THREADS "${BLIS_NUM_THREADS:-$effective}"
clamp_thread_var VECLIB_MAXIMUM_THREADS "${VECLIB_MAXIMUM_THREADS:-$effective}"
clamp_thread_var PADDLE_NUM_THREADS "${PADDLE_NUM_THREADS:-$effective}"
clamp_thread_var RAYON_NUM_THREADS "${RAYON_NUM_THREADS:-$effective}"

affinity_enabled="${WEB_OSINT_CPU_GUARD_AFFINITY:-1}"
affinity_range=""
if [[ "$affinity_enabled" =~ ^(1|true|yes|on)$ ]] && command -v taskset >/dev/null 2>&1; then
  if [[ "$effective" -eq 1 ]]; then
    affinity_range="0"
  else
    affinity_range="0-$((effective - 1))"
  fi
fi

echo "[web-osint-cpu-guard] total=$WEB_OSINT_CPU_TOTAL_THREADS reserved=$WEB_OSINT_CPU_RESERVED_THREADS effective=$WEB_OSINT_CPU_EFFECTIVE_THREADS affinity=${affinity_range:-none} qwen_torch=$QWEN_INFERENCE_TORCH_THREADS omp=$OMP_NUM_THREADS mkl=$MKL_NUM_THREADS openblas=$OPENBLAS_NUM_THREADS paddle=$PADDLE_NUM_THREADS" >&2

if [[ -n "$affinity_range" ]]; then
  exec taskset -c "$affinity_range" "$@"
fi

exec "$@"
