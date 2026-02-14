# Benchmark Results - 2026-02-14

## YABS Disk I/O

| storage_class | block_size | read_mb_s | read_iops | write_mb_s | write_iops | total_mb_s | total_iops |
| --- | --- | --- | --- | --- | --- | --- | ---  |
| freenas-iscsi-cold-csi | 4k | 66.85 | 16320 | 66.97 | 16351 | 133.82 | 32671 |
| freenas-iscsi-cold-csi | 64k | 405.35 | 6185 | 407.48 | 6217 | 812.82 | 12402 |
| freenas-iscsi-cold-csi | 512k | 6.69 | 12 | 7.26 | 13 | 13.95 | 25 |
| freenas-iscsi-cold-csi | 1m | 195.77 | 186 | 208.81 | 199 | 404.57 | 385 |
| freenas-iscsi-fast-csi | 4k | 66.39 | 16208 | 66.52 | 16239 | 132.90 | 32447 |
| freenas-iscsi-fast-csi | 64k | 400.57 | 6112 | 402.68 | 6144 | 803.25 | 12256 |
| freenas-iscsi-fast-csi | 512k | 132.89 | 253 | 139.96 | 266 | 272.85 | 519 |
| freenas-iscsi-fast-csi | 1m | 238.36 | 227 | 254.24 | 242 | 492.60 | 469 |
| freenas-iscsi-ssd-csi | 4k | 66.02 | 16118 | 66.14 | 16147 | 132.16 | 32265 |
| freenas-iscsi-ssd-csi | 64k | 420.63 | 6418 | 422.84 | 6452 | 843.47 | 12870 |
| freenas-iscsi-ssd-csi | 512k | 218.36 | 416 | 229.96 | 438 | 448.33 | 854 |
| freenas-iscsi-ssd-csi | 1m | 176.65 | 168 | 188.41 | 179 | 365.06 | 347 |
| lvms-vg1-worker | 4k | 346.69 | 84642 | 347.61 | 84865 | 694.30 | 169507 |
| lvms-vg1-worker | 64k | 1603.18 | 24462 | 1611.62 | 24591 | 3214.79 | 49053 |
| lvms-vg1-worker | 512k | 2529.51 | 4824 | 2663.92 | 5081 | 5193.43 | 9905 |
| lvms-vg1-worker | 1m | 2973.21 | 2835 | 3171.23 | 3024 | 6144.44 | 5859 |
| freenas-nfs-cold-csi | 4k | 0.33 | 80 | 0.35 | 84 | 0.68 | 164 |
| freenas-nfs-cold-csi | 64k | 1.71 | 26 | 1.87 | 28 | 3.58 | 54 |
| freenas-nfs-cold-csi | 512k | 20.89 | 39 | 22.47 | 42 | 43.36 | 81 |
| freenas-nfs-cold-csi | 1m | 15.64 | 14 | 17.45 | 16 | 33.09 | 30 |
| freenas-nfs-fast-csi | 4k | 34.48 | 8418 | 34.57 | 8438 | 69.05 | 16856 |
| freenas-nfs-fast-csi | 64k | 367.57 | 5608 | 369.51 | 5638 | 737.08 | 11246 |
| freenas-nfs-fast-csi | 512k | 1005.72 | 1918 | 1059.16 | 2020 | 2064.89 | 3938 |
| freenas-nfs-fast-csi | 1m | 1014.78 | 967 | 1082.37 | 1032 | 2097.15 | 1999 |
| freenas-nfs-ssd-csi | 4k | 10.25 | 2501 | 10.28 | 2508 | 20.52 | 5009 |
| freenas-nfs-ssd-csi | 64k | 118.15 | 1802 | 118.77 | 1812 | 236.92 | 3614 |
| freenas-nfs-ssd-csi | 512k | 343.56 | 655 | 361.81 | 690 | 705.36 | 1345 |
| freenas-nfs-ssd-csi | 1m | 381.20 | 363 | 406.58 | 387 | 787.78 | 750 |
| freenas-nvmeof-cold-csi | 4k | 335.21 | 81837 | 336.09 | 82053 | 671.30 | 163890 |
| freenas-nvmeof-cold-csi | 64k | 679.74 | 10371 | 683.31 | 10426 | 1363.05 | 20797 |
| freenas-nvmeof-cold-csi | 512k | 105.34 | 200 | 110.94 | 211 | 216.28 | 411 |
| freenas-nvmeof-cold-csi | 1m | 107.72 | 102 | 114.89 | 109 | 222.61 | 211 |
| freenas-nvmeof-fast-csi | 4k | 327.13 | 79865 | 327.99 | 80076 | 655.12 | 159941 |
| freenas-nvmeof-fast-csi | 64k | 1177.49 | 17967 | 1183.68 | 18061 | 2361.17 | 36028 |
| freenas-nvmeof-fast-csi | 512k | 1566.97 | 2988 | 1650.23 | 3147 | 3217.20 | 6135 |
| freenas-nvmeof-fast-csi | 1m | 1454.36 | 1386 | 1551.22 | 1479 | 3005.57 | 2865 |
| freenas-nvmeof-ssd-csi | 4k | 336.84 | 82236 | 337.73 | 82453 | 674.57 | 164689 |
| freenas-nvmeof-ssd-csi | 64k | 1208.04 | 18433 | 1214.39 | 18530 | 2422.43 | 36963 |
| freenas-nvmeof-ssd-csi | 512k | 1421.13 | 2710 | 1496.64 | 2854 | 2917.78 | 5564 |
| freenas-nvmeof-ssd-csi | 1m | 1542.89 | 1471 | 1645.65 | 1569 | 3188.54 | 3040 |

## Latency

| job_name | storage_class | pvc_pending_ms | pvc_binding_ms | job_completion_ms |
| --- | --- | --- | --- | ---  |
| iscsi-cold | freenas-iscsi-cold-csi | 8 | 63759 | 361000 |
| iscsi-fast | freenas-iscsi-fast-csi | 4 | 12364 | 92000 |
| iscsi-ssd | freenas-iscsi-ssd-csi | 3 | 13975 | 100000 |
| lvms-vg1-worker | lvms-vg1-worker | 27 | 1166 | 24000 |
| nfs-cold | freenas-nfs-cold-csi | 12 | 26656 | 285000 |
| nfs-fast | freenas-nfs-fast-csi | 5 | 9085 | 74000 |
| nfs-ssd | freenas-nfs-ssd-csi | 8 | 7660 | 93000 |
| nvmeof-cold | freenas-nvmeof-cold-csi | 3 | 15528 | 128000 |
| nvmeof-fast | freenas-nvmeof-fast-csi | 7 | 9143 | 43000 |
| nvmeof-ssd | freenas-nvmeof-ssd-csi | 7 | 10044 | 51000 |
