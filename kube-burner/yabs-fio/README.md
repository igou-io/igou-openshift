# yabs-fio

A [kube-burner](https://github.com/kube-burner/kube-burner) workload that benchmarks storage performance across multiple CSI storage classes using [YABS](https://github.com/masonr/yet-another-bench-script).

## Disable zfs cache for testing

```bash
zfs set primarycache=none cold
zfs set secondarycache=none cold
zfs set primarycache=none fast
zfs set secondarycache=none fast
zfs set primarycache=none ssd
zfs set secondarycache=none ssd
```


## Running

```bash
kube-burner init -c yabs-fio.yml
```

The config sets `gc: false`, so the namespace and resources will persist after the run completes. This lets you inspect results before cleaning up manually.

## Getting all job pod logs

To retrieve logs from every pod created by the jobs in the `yabs-fio` namespace:

```bash
kubectl get pods -n yabs-fio -o name | xargs -I{} sh -c 'echo "=== {} ===" && kubectl logs -n yabs-fio {}'
```

## Cleanup

Since garbage collection is disabled, remove the namespace manually when finished:

```bash
kubectl delete namespace yabs-fio
```
## Storage Pools

The storage classes map to TrueNAS ZFS pools with different backing hardware:

| Pool | Drives | Layout |
| --- | --- | --- |
| cold | 6x 3TB 7200 RPM HDD | RAIDZ2 |
| ssd | 4x 2TB SATA SSD | Mirror (2-wide) |
| fast | 4x 1TB NVMe | Mirror (2-wide) |

Each pool is exposed over both NFS and NVMe-oF, giving 6 storage classes total (e.g. `freenas-nfs-cold-csi`, `freenas-nvmeof-cold-csi`).

`lvms-vg1-worker` is direct i/o to a local NVMe drive via LVM operator

# Benchmark Results - 2026-02-13

## YABS (FIO, Random Read/Write) Disk I/O

| storage_class | block_size | read_mb_s | read_iops | write_mb_s | write_iops | total_mb_s | total_iops |
| --- | --- | --- | --- | --- | --- | --- | ---  |
| freenas-iscsi-cold-csi | 4k | 50.88 | 12422 | 50.98 | 12445 | 101.86 | 24867 |
| freenas-iscsi-cold-csi | 64k | 276.62 | 4220 | 278.07 | 4243 | 554.69 | 8463 |
| freenas-iscsi-cold-csi | 512k | 159.03 | 303 | 167.48 | 319 | 326.51 | 622 |
| freenas-iscsi-cold-csi | 1m | 120.32 | 114 | 128.33 | 122 | 248.65 | 236 |
| freenas-iscsi-fast-csi | 4k | 69.82 | 17046 | 70.03 | 17096 | 139.85 | 34142 |
| freenas-iscsi-fast-csi | 64k | 448.08 | 6837 | 450.44 | 6873 | 898.53 | 13710 |
| freenas-iscsi-fast-csi | 512k | 133.39 | 254 | 140.47 | 267 | 273.86 | 521 |
| freenas-iscsi-fast-csi | 1m | 254.35 | 242 | 271.29 | 258 | 525.63 | 500 |
| freenas-iscsi-ssd-csi | 4k | 66.07 | 16130 | 66.19 | 16159 | 132.26 | 32289 |
| freenas-iscsi-ssd-csi | 64k | 429.74 | 6557 | 432.01 | 6591 | 861.75 | 13148 |
| freenas-iscsi-ssd-csi | 512k | 387.18 | 738 | 407.75 | 777 | 794.92 | 1515 |
| freenas-iscsi-ssd-csi | 1m | 243.61 | 232 | 259.84 | 247 | 503.45 | 479 |
| freenas-nfs-cold-csi | 4k | 0.25 | 60 | 0.26 | 63 | 0.51 | 123 |
| freenas-nfs-cold-csi | 64k | 11.15 | 170 | 11.70 | 178 | 22.85 | 348 |
| freenas-nfs-cold-csi | 512k | 21.32 | 40 | 22.89 | 43 | 44.21 | 83 |
| freenas-nfs-cold-csi | 1m | 33.19 | 31 | 36.21 | 34 | 69.39 | 65 |
| freenas-nfs-fast-csi | 4k | 34.05 | 8312 | 34.11 | 8328 | 68.16 | 16640 |
| freenas-nfs-fast-csi | 64k | 357.15 | 5449 | 359.03 | 5478 | 716.18 | 10927 |
| freenas-nfs-fast-csi | 512k | 936.81 | 1786 | 986.59 | 1881 | 1923.40 | 3667 |
| freenas-nfs-fast-csi | 1m | 1050.70 | 1002 | 1120.67 | 1068 | 2171.37 | 2070 |
| freenas-nfs-ssd-csi | 4k | 10.90 | 2661 | 10.92 | 2667 | 21.82 | 5328 |
| freenas-nfs-ssd-csi | 64k | 120.15 | 1833 | 120.78 | 1843 | 240.94 | 3676 |
| freenas-nfs-ssd-csi | 512k | 346.57 | 661 | 364.99 | 696 | 711.56 | 1357 |
| freenas-nfs-ssd-csi | 1m | 387.38 | 369 | 413.18 | 394 | 800.55 | 763 |
| freenas-nvmeof-cold-csi | 4k | 66.25 | 16174 | 66.37 | 16203 | 132.62 | 32377 |
| freenas-nvmeof-cold-csi | 64k | 67.60 | 1031 | 68.01 | 1037 | 135.61 | 2068 |
| freenas-nvmeof-cold-csi | 512k | 332.42 | 634 | 350.08 | 667 | 682.50 | 1301 |
| freenas-nvmeof-cold-csi | 1m | 56.51 | 53 | 60.22 | 57 | 116.74 | 110 |
| freenas-nvmeof-fast-csi | 4k | 314.14 | 76695 | 314.97 | 76897 | 629.11 | 153592 |
| freenas-nvmeof-fast-csi | 64k | 1123.74 | 17146 | 1129.65 | 17237 | 2253.39 | 34383 |
| freenas-nvmeof-fast-csi | 512k | 1539.30 | 2935 | 1621.09 | 3091 | 3160.39 | 6026 |
| freenas-nvmeof-fast-csi | 1m | 1511.47 | 1441 | 1612.14 | 1537 | 3123.61 | 2978 |
| freenas-nvmeof-ssd-csi | 4k | 328.38 | 80171 | 329.25 | 80382 | 657.63 | 160553 |
| freenas-nvmeof-ssd-csi | 64k | 1047.87 | 15989 | 1053.38 | 16073 | 2101.26 | 32062 |
| freenas-nvmeof-ssd-csi | 512k | 1635.58 | 3119 | 1722.48 | 3285 | 3358.07 | 6404 |
| freenas-nvmeof-ssd-csi | 1m | 1681.45 | 1603 | 1793.44 | 1710 | 3474.89 | 3313 |
| lvms-vg1-worker | 4k | 359.06 | 87660 | 360.01 | 87892 | 719.06 | 175552 |
| lvms-vg1-worker | 64k | 1543.12 | 23546 | 1551.24 | 23670 | 3094.36 | 47216 |
| lvms-vg1-worker | 512k | 2429.63 | 4634 | 2558.72 | 4880 | 4988.35 | 9514 |
| lvms-vg1-worker | 1m | 2981.75 | 2843 | 3180.33 | 3032 | 6162.08 | 5875 |

## Latency (Kubernetes)

| job_name | storage_class | pvc_pending_ms | pvc_binding_ms | job_completion_ms |
| --- | --- | --- | --- | ---  |
| iscsi-cold | freenas-iscsi-cold-csi | 13 | 161210 | 412000 |
| iscsi-fast | freenas-iscsi-fast-csi | 9 | 13426 | 95000 |
| iscsi-ssd | freenas-iscsi-ssd-csi | 10 | 14745 | 90000 |
| nfs-cold | freenas-nfs-cold-csi | 4 | 41967 | 243000 |
| nfs-fast | freenas-nfs-fast-csi | 12 | 8579 | 71000 |
| nfs-ssd | freenas-nfs-ssd-csi | 8 | 7576 | 91000 |
| nvmeof-cold | freenas-nvmeof-cold-csi | 2 | 19356 | 187000 |
| nvmeof-fast | freenas-nvmeof-fast-csi | 3 | 7822 | 47000 |
| nvmeof-ssd | freenas-nvmeof-ssd-csi | 3 | 39195 | 73000 |
| lvms-vg1-worker | lvms-vg1-worker | 26 | 1081 | 25000 |

## YABS (FIO, Random Read/Write) CACHE DISABLED


| storage_class | block_size | read_mb_s | read_iops | write_mb_s | write_iops | total_mb_s | total_iops |
| --- | --- | --- | --- | --- | --- | --- | ---  |
| freenas-iscsi-fast-csi | 4k | 71.85 | 17541 | 72.04 | 17587 | 143.89 | 35128 |
| freenas-iscsi-fast-csi | 64k | 420.22 | 6412 | 422.43 | 6445 | 842.65 | 12857 |
| freenas-iscsi-fast-csi | 512k | 262.90 | 501 | 276.87 | 528 | 539.77 | 1029 |
| freenas-iscsi-fast-csi | 1m | 271.85 | 259 | 289.95 | 276 | 561.80 | 535 |
| freenas-iscsi-ssd-csi | 4k | 54.40 | 13281 | 54.49 | 13302 | 108.89 | 26583 |
| freenas-iscsi-ssd-csi | 64k | 355.73 | 5428 | 357.60 | 5456 | 713.33 | 10884 |
| freenas-iscsi-ssd-csi | 512k | 232.07 | 442 | 244.40 | 466 | 476.48 | 908 |
| freenas-iscsi-ssd-csi | 1m | 257.40 | 245 | 274.55 | 261 | 531.95 | 506 |
| lvms-vg1-worker | 4k | 344.13 | 84017 | 345.04 | 84239 | 689.18 | 168256 |
| lvms-vg1-worker | 64k | 1592.45 | 24298 | 1600.83 | 24426 | 3193.28 | 48724 |
| lvms-vg1-worker | 512k | 2455.29 | 4683 | 2585.75 | 4931 | 5041.04 | 9614 |
| lvms-vg1-worker | 1m | 2947.91 | 2811 | 3144.24 | 2998 | 6092.15 | 5809 |
| freenas-nfs-cold-csi | 4k | 0.06 | 13 | 0.06 | 15 | 0.12 | 28 |
| freenas-nfs-cold-csi | 64k | 2.28 | 34 | 2.49 | 37 | 4.77 | 71 |
| freenas-nfs-cold-csi | 512k | 8.42 | 16 | 9.06 | 17 | 17.48 | 33 |
| freenas-nfs-cold-csi | 1m | 14.52 | 13 | 15.98 | 15 | 30.50 | 28 |
| freenas-nfs-fast-csi | 4k | 31.60 | 7715 | 31.63 | 7722 | 63.23 | 15437 |
| freenas-nfs-fast-csi | 64k | 348.49 | 5317 | 350.33 | 5345 | 698.82 | 10662 |
| freenas-nfs-fast-csi | 512k | 1052.80 | 2008 | 1108.73 | 2114 | 2161.53 | 4122 |
| freenas-nfs-fast-csi | 1m | 1253.48 | 1195 | 1336.97 | 1275 | 2590.45 | 2470 |
| freenas-nfs-ssd-csi | 4k | 7.32 | 1787 | 7.34 | 1793 | 14.66 | 3580 |
| freenas-nfs-ssd-csi | 64k | 92.91 | 1417 | 93.40 | 1425 | 186.32 | 2842 |
| freenas-nfs-ssd-csi | 512k | 296.09 | 564 | 311.83 | 594 | 607.92 | 1158 |
| freenas-nfs-ssd-csi | 1m | 335.86 | 320 | 358.22 | 341 | 694.08 | 661 |
| freenas-nvmeof-cold-csi | 4k | 0.40 | 98 | 0.42 | 103 | 0.83 | 201 |
| freenas-nvmeof-cold-csi | 64k | 11.77 | 179 | 12.33 | 188 | 24.10 | 367 |
| freenas-nvmeof-cold-csi | 512k | 18.78 | 35 | 20.17 | 38 | 38.95 | 73 |
| freenas-nvmeof-cold-csi | 1m | 4.75 | 4 | 5.02 | 4 | 9.77 | 8 |
| freenas-nvmeof-fast-csi | 4k | 284.06 | 69350 | 284.81 | 69533 | 568.87 | 138883 |
| freenas-nvmeof-fast-csi | 64k | 1207.35 | 18422 | 1213.71 | 18519 | 2421.06 | 36941 |
| freenas-nvmeof-fast-csi | 512k | 1460.83 | 2786 | 1538.45 | 2934 | 2999.28 | 5720 |
| freenas-nvmeof-fast-csi | 1m | 1494.09 | 1424 | 1593.59 | 1519 | 3087.68 | 2943 |
| freenas-nvmeof-ssd-csi | 4k | 64.49 | 15743 | 64.60 | 15771 | 129.08 | 31514 |
| freenas-nvmeof-ssd-csi | 64k | 515.36 | 7863 | 518.07 | 7905 | 1033.44 | 15768 |
| freenas-nvmeof-ssd-csi | 512k | 914.30 | 1743 | 962.87 | 1836 | 1877.17 | 3579 |
| freenas-nvmeof-ssd-csi | 1m | 1275.80 | 1216 | 1360.77 | 1297 | 2636.57 | 2513 |

## Latency

| job_name | storage_class | pvc_pending_ms | pvc_binding_ms | job_completion_ms |
| --- | --- | --- | --- | ---  |
| iscsi-cold | freenas-iscsi-cold-csi | 3 | 168843 | 471000 |
| iscsi-fast | freenas-iscsi-fast-csi | 7 | 12455 | 88000 |
| iscsi-ssd | freenas-iscsi-ssd-csi | 6 | 30922 | 132000 |
| lvms-vg1-worker | lvms-vg1-worker | 26 | 1108 | 24000 |
| nfs-cold | freenas-nfs-cold-csi | 3 | 18590 | 243000 |
| nfs-fast | freenas-nfs-fast-csi | 11 | 13685 | 82000 |
| nfs-ssd | freenas-nfs-ssd-csi | 5 | 8774 | 99000 |
| nvmeof-cold | freenas-nvmeof-cold-csi | 8 | 22710 | 560000 |
| nvmeof-fast | freenas-nvmeof-fast-csi | 2 | 10485 | 49000 |
| nvmeof-ssd | freenas-nvmeof-ssd-csi | 7 | 8479 | 97000 |
