# Benchmark Results - 2026-02-14

## YABS Disk I/O

| storage_class | block_size | read_mb_s | read_iops | write_mb_s | write_iops | total_mb_s | total_iops |
| --- | --- | --- | --- | --- | --- | --- | ---  |
| freenas-iscsi-cold-csi | 4k | 67.19 | 16404 | 67.33 | 16438 | 134.52 | 32842 |
| freenas-iscsi-cold-csi | 64k | 398.33 | 6078 | 400.43 | 6110 | 798.77 | 12188 |
| freenas-iscsi-cold-csi | 512k | 270.10 | 515 | 284.45 | 542 | 554.55 | 1057 |
| freenas-iscsi-cold-csi | 1m | 259.98 | 247 | 277.29 | 264 | 537.27 | 511 |
| freenas-iscsi-fast-csi | 4k | 67.94 | 16587 | 68.09 | 16622 | 136.03 | 33209 |
| freenas-iscsi-fast-csi | 64k | 418.00 | 6378 | 420.20 | 6411 | 838.21 | 12789 |
| freenas-iscsi-fast-csi | 512k | 233.21 | 444 | 245.60 | 468 | 478.81 | 912 |
| freenas-iscsi-fast-csi | 1m | 122.79 | 117 | 130.96 | 124 | 253.75 | 241 |
| freenas-iscsi-ssd-csi | 4k | 68.91 | 16822 | 69.07 | 16862 | 137.97 | 33684 |
| freenas-iscsi-ssd-csi | 64k | 425.22 | 6488 | 427.46 | 6522 | 852.68 | 13010 |
| freenas-iscsi-ssd-csi | 512k | 236.96 | 451 | 249.55 | 475 | 486.52 | 926 |
| freenas-iscsi-ssd-csi | 1m | 161.63 | 154 | 172.40 | 164 | 334.03 | 318 |
| lvms-vg1-worker | 4k | 344.74 | 84166 | 345.65 | 84388 | 690.40 | 168554 |
| lvms-vg1-worker | 64k | 1564.53 | 23872 | 1572.77 | 23998 | 3137.30 | 47870 |
| lvms-vg1-worker | 512k | 2502.28 | 4772 | 2635.24 | 5026 | 5137.52 | 9798 |
| lvms-vg1-worker | 1m | 2973.21 | 2835 | 3171.23 | 3024 | 6144.44 | 5859 |
| freenas-nfs-cold-csi | 4k | 1.27 | 310 | 1.30 | 318 | 2.58 | 628 |
| freenas-nfs-cold-csi | 64k | 3.05 | 46 | 3.22 | 49 | 6.28 | 95 |
| freenas-nfs-cold-csi | 512k | 89.04 | 169 | 93.77 | 178 | 182.81 | 347 |
| freenas-nfs-cold-csi | 1m | 58.90 | 56 | 62.89 | 59 | 121.80 | 115 |
| freenas-nfs-fast-csi | 4k | 33.23 | 8111 | 33.28 | 8126 | 66.51 | 16237 |
| freenas-nfs-fast-csi | 64k | 355.73 | 5428 | 357.60 | 5456 | 713.33 | 10884 |
| freenas-nfs-fast-csi | 512k | 1010.58 | 1927 | 1064.28 | 2029 | 2074.86 | 3956 |
| freenas-nfs-fast-csi | 1m | 1049.10 | 1000 | 1118.97 | 1067 | 2168.08 | 2067 |
| freenas-nfs-ssd-csi | 4k | 10.12 | 2470 | 10.15 | 2478 | 20.27 | 4948 |
| freenas-nfs-ssd-csi | 64k | 121.03 | 1846 | 121.67 | 1856 | 242.71 | 3702 |
| freenas-nfs-ssd-csi | 512k | 340.87 | 650 | 358.98 | 684 | 699.85 | 1334 |
| freenas-nfs-ssd-csi | 1m | 28.19 | 26 | 30.84 | 29 | 59.03 | 55 |
| freenas-nvmeof-cold-csi | 4k | 62.84 | 15342 | 62.97 | 15373 | 125.81 | 30715 |
| freenas-nvmeof-cold-csi | 64k | 329.41 | 5026 | 331.15 | 5052 | 660.56 | 10078 |
| freenas-nvmeof-cold-csi | 512k | 1654.99 | 3156 | 1742.92 | 3324 | 3397.92 | 6480 |
| freenas-nvmeof-cold-csi | 1m | 75.84 | 72 | 80.89 | 77 | 156.74 | 149 |
| freenas-nvmeof-fast-csi | 4k | 318.15 | 77673 | 318.99 | 77878 | 637.14 | 155551 |
| freenas-nvmeof-fast-csi | 64k | 1137.47 | 17356 | 1143.45 | 17447 | 2280.92 | 34803 |
| freenas-nvmeof-fast-csi | 512k | 1522.50 | 2903 | 1603.39 | 3058 | 3125.88 | 5961 |
| freenas-nvmeof-fast-csi | 1m | 1417.65 | 1351 | 1512.07 | 1442 | 2929.72 | 2793 |
| freenas-nvmeof-ssd-csi | 4k | 330.96 | 80802 | 331.84 | 81015 | 662.80 | 161817 |
| freenas-nvmeof-ssd-csi | 64k | 1242.37 | 18957 | 1248.91 | 19056 | 2491.28 | 38013 |
| freenas-nvmeof-ssd-csi | 512k | 1518.08 | 2895 | 1598.74 | 3049 | 3116.81 | 5944 |
| freenas-nvmeof-ssd-csi | 1m | 1168.23 | 1114 | 1246.03 | 1188 | 2414.26 | 2302 |

## Latency

| job_name | storage_class | pvc_pending_ms | pvc_binding_ms | job_completion_ms |
| --- | --- | --- | --- | ---  |
| iscsi-cold | freenas-iscsi-cold-csi | 8 | 244119 | 398000 |
| iscsi-fast | freenas-iscsi-fast-csi | 8 | 13296 | 98000 |
| iscsi-ssd | freenas-iscsi-ssd-csi | 7 | 12432 | 100000 |
| lvms-vg1-worker | lvms-vg1-worker | 28 | 1150 | 24000 |
| nfs-cold | freenas-nfs-cold-csi | 3 | 21883 | 192000 |
| nfs-fast | freenas-nfs-fast-csi | 8 | 7257 | 67000 |
| nfs-ssd | freenas-nfs-ssd-csi | 7 | 9935 | 120000 |
| nvmeof-cold | freenas-nvmeof-cold-csi | 2 | 23317 | 135000 |
| nvmeof-fast | freenas-nvmeof-fast-csi | 4 | 8539 | 48000 |
| nvmeof-ssd | freenas-nvmeof-ssd-csi | 12 | 8922 | 52000 |
