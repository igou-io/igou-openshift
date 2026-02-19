# Restoring a Backup from a tar.gz on a Remote Machine

Follow these steps to restore your Minecraft server backup:

1. **Create an idle pod**
    Deploy a pod that mounts the same PVC as your Minecraft server, but does nothing (just sleeps).
    _See `restore-backup-idle-pod.yaml` for an example._

2. **Copy backup files to the pod**
    Use `oc rsync` to transfer your local backup directory to `/backups` on the pod.

3. **Access the pod shell**
    Run `oc rsh` to open a shell in the pod.

4. **Remove existing data**
    ```sh
    rm -rf /data/{*,.*}
    ```

5. **Navigate to backups directory**
    ```sh
    cd /backups
    ```

6. **Restore the backup**
    ```sh
    restore-tar-backup
    ```