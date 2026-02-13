# pod-job-pvc

A [kube-burner](https://github.com/kube-burner/kube-burner) workload that benchmarks storage performance across multiple CSI storage classes using [YABS](https://github.com/masonr/yet-another-bench-script).

## What it does

For each storage class defined in `pod-job-pvc.yml`, the workload:

1. Creates a PVC with the specified storage class and size
2. Launches a Kubernetes Job that mounts the PVC
3. Runs YABS (Yet Another Bench Script) disk I/O benchmarks on the mounted volume
4. Outputs parsed results (read/write speeds in MB/s and IOPS) at block sizes of 4k, 64k, 512k, and 1m

By default, the following storage classes are tested:

- `freenas-nfs-fast-csi`
- `freenas-nfs-ssd-csi`
- `freenas-nfs-cold-csi`
- `freenas-nvmeof-fast-csi`
- `freenas-nvmeof-ssd-csi`
- `freenas-nvmeof-cold-csi`

## Running

```bash
kube-burner init -c pod-job-pvc.yml
```

The config sets `gc: false`, so the namespace and resources will persist after the run completes. This lets you inspect results before cleaning up manually.

## Getting all job pod logs

To retrieve logs from every pod created by the jobs in the `pod-job-pvc` namespace:

```bash
kubectl get pods -n pod-job-pvc -o name | xargs -I{} sh -c 'echo "=== {} ===" && kubectl logs -n pod-job-pvc {}'
```

## Cleanup

Since garbage collection is disabled, remove the namespace manually when finished:

```bash
kubectl delete namespace pod-job-pvc
```

## Results

### 25GbE - 2026-02-13

Mixed R/W 50/50 total throughput (read + write combined). Full logs in [results/25gbe-2026-02-13.txt](results/25gbe-2026-02-13.txt).

| Storage Class | 4k | 64k | 512k | 1m |
|---|---|---|---|---|
| nfs-cold | 3.10 MB/s (776) | 39.98 MB/s (624) | 51.55 MB/s (100) | 47.10 MB/s (45) |
| nfs-ssd | 9.72 MB/s (2.4k) | 122.88 MB/s (1.9k) | 28.93 MB/s (55) | 181.48 MB/s (176) |
| nfs-fast | 11.45 MB/s (2.8k) | 134.06 MB/s (2.0k) | 815.06 MB/s (1.5k) | 1.24 MB/s (0) |
| nvmeof-cold | 69.63 MB/s (17.4k) | 254.09 MB/s (3.9k) | 1.53 GB/s (3.0k) | 2.01 GB/s (1.9k) |
| nvmeof-ssd | 450.85 MB/s (112.7k) | 1.37 GB/s (21.5k) | 2.88 GB/s (5.6k) | 2.85 GB/s (2.7k) |
| nvmeof-fast | 612.12 MB/s (153.0k) | 2.24 GB/s (35.0k) | 2.97 GB/s (5.8k) | 2.48 GB/s (2.4k) |
