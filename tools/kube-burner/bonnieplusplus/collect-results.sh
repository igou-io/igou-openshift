#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
METRICS_DIR="${SCRIPT_DIR}/collected-metrics"
RESULTS_DIR="${SCRIPT_DIR}/results"
DATE=$(date +%Y-%m-%d)
usage() {
  echo "Usage: $0 <filename>" >&2
  echo "" >&2
  echo "Collects bonnie++ benchmark and kube-burner latency results into CSV files" >&2
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

# Collect bonnie++ benchmark CSV from pod logs
# bonnie++ 2.00 CSV fields (with per-char tests enabled):
#   $3  = name (storage class, from -m flag)
#   $10 = putc (per-char write, K/s)
#   $12 = put_block (sequential write, K/s)
#   $14 = rewrite (K/s)
#   $16 = getc (per-char read, K/s)
#   $18 = get_block (sequential read, K/s)
#   $20 = seeks (/s, may be +++++ if too fast)
#   $27 = seq_create (/s)    $29 = seq_stat (/s)    $31 = seq_del (/s)
#   $33 = ran_create (/s)    $35 = ran_stat (/s)    $37 = ran_del (/s)
echo "Collecting benchmark results from pod logs..."
{
  echo "storage_class,putc_KBs,seq_write_MBs,seq_rewrite_MBs,getc_KBs,seq_read_MBs,random_seeks,seq_create,seq_stat,seq_del,ran_create,ran_stat,ran_del"
  kubectl get pods -n bonnieplusplus -o name | \
    xargs -I{} kubectl logs -n bonnieplusplus {} | \
    grep -E '^[0-9]+\.[0-9]+,[0-9]+\.[0-9]+,' | \
    awk -F',' '{
      name=$3
      putc      = $10
      put_block = ($12 != "" && $12+0 == $12) ? sprintf("%.1f", $12/1024) : $12
      rewrite   = ($14 != "" && $14+0 == $14) ? sprintf("%.1f", $14/1024) : $14
      getc      = $16
      get_block = ($18 != "" && $18+0 == $18) ? sprintf("%.1f", $18/1024) : $18
      seeks = $20
      printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n", \
        name, putc, put_block, rewrite, getc, get_block, seeks, $27, $29, $31, $33, $35, $37
    }'
} > "$BENCH_CSV"
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
  echo "# Bonnie++ Benchmark Results - ${DATE}"
  echo ""
  echo "## Bonnie++ Disk I/O"
  echo ""
  csv_to_markdown "$BENCH_CSV"
  echo ""
  echo "## Latency"
  echo ""
  csv_to_markdown "$LATENCY_CSV"
} > "$MD_FILE"

echo "Wrote $MD_FILE"
