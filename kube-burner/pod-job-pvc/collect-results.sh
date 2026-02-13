#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
METRICS_DIR="${SCRIPT_DIR}/collected-metrics"
RESULTS_DIR="${SCRIPT_DIR}/results"
DATE=$(date +%Y-%m-%d)
usage() {
  echo "Usage: $0 <filename>" >&2
  echo "" >&2
  echo "Collects YABS benchmark and kube-burner latency results into CSV files" >&2
  echo "and a markdown summary. Files are written to results/<filename>-YYYY-MM-DD.*" >&2
  exit 1
}

csv_to_markdown() {
  local file="$1"
  local first=true
  while IFS= read -r line; do
    echo "| $(echo "$line" | sed 's/,/ | /g') |"
    if $first; then
      echo "$line" | sed 's/[^,]*/ --- /g; s/,/|/g; s/^/|/; s/$/ |/'
      first=false
    fi
  done < "$file"
}

if [ $# -ne 1 ]; then
  usage
fi

FILENAME="$1"

mkdir -p "$RESULTS_DIR"

BENCH_CSV="${RESULTS_DIR}/${FILENAME}-${DATE}.csv"
LATENCY_CSV="${RESULTS_DIR}/${FILENAME}-${DATE}-latency.csv"

# Collect YABS benchmark CSV from pod logs
echo "Collecting benchmark results from pod logs..."
kubectl get pods -n pod-job-pvc -o name | \
  xargs -I{} kubectl logs -n pod-job-pvc {} | \
  awk '/^storage_class,/{if(!h++)print;next} /,(4k|64k|512k|1m),/{print}' > "$BENCH_CSV"
echo "Wrote $BENCH_CSV"

# Collect latency CSV from kube-burner metrics
echo "Collecting latency metrics from collected-metrics/..."
echo "job_name,storage_class,pvc_pending_ms,pvc_binding_ms,job_completion_ms" > "$LATENCY_CSV"

for pvc_file in "$METRICS_DIR"/pvcLatencyMeasurement-*.json; do
  [ -f "$pvc_file" ] || continue
  job_name=$(jq -r '.[0].jobName' "$pvc_file")
  storage_class=$(jq -r '.[0].storageClass' "$pvc_file")
  pvc_pending=$(jq -r '.[0].pendingLatency' "$pvc_file")
  pvc_binding=$(jq -r '.[0].bindingLatency' "$pvc_file")

  job_file="${METRICS_DIR}/jobLatencyMeasurement-${job_name}.json"
  if [ -f "$job_file" ]; then
    job_completion=$(jq -r '.[0].completionLatency' "$job_file")
  else
    job_completion="N/A"
  fi

  echo "${job_name},${storage_class},${pvc_pending},${pvc_binding},${job_completion}" >> "$LATENCY_CSV"
done
echo "Wrote $LATENCY_CSV"

# Generate markdown summary
MD_FILE="${RESULTS_DIR}/${FILENAME}-${DATE}.md"

{
  echo "# Benchmark Results - ${DATE}"
  echo ""
  echo "## YABS Disk I/O"
  echo ""
  csv_to_markdown "$BENCH_CSV"
  echo ""
  echo "## Latency"
  echo ""
  csv_to_markdown "$LATENCY_CSV"
} > "$MD_FILE"

echo "Wrote $MD_FILE"
