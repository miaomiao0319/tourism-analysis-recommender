#!/bin/sh
# Execute as root in WSL: sh scripts/sync-data-wsl.sh <existing-ordinary-user>
# Mount only for this invocation; do not alter /etc/wsl.conf or the existing /mnt/c mount.
set -eu

if [ "$(id -u)" -ne 0 ] || [ "$#" -ne 1 ]; then
    echo 'Run as root with one existing non-root Linux username.' >&2
    exit 2
fi
user=$1
user_uid=$(id -u "$user")
user_gid=$(id -g "$user")
if [ "$user_uid" -eq 0 ]; then
    echo 'The installation user must not be root.' >&2
    exit 2
fi
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
case "$project" in
    /mnt/c/*) relative=${project#/mnt/c/} ;;
    *) echo 'This entry point only supports a project on /mnt/c.' >&2; exit 2 ;;
esac
test -f "$project/uv.lock" && test -f "$project/pyproject.toml"
uv_bin=$(getent passwd "$user" | cut -d: -f6)/.local/bin/uv
test -x "$uv_bin"
mount_dir=/mnt/tourism-workspace
mkdir -p "$mount_dir"
if mountpoint -q "$mount_dir" || [ -n "$(ls -A "$mount_dir")" ]; then
    echo 'Temporary mount directory is occupied; preserve it and stop.' >&2
    exit 1
fi
mount -t drvfs C: "$mount_dir" -o "uid=$user_uid,gid=$user_gid,metadata"
trap 'umount "$mount_dir"' EXIT HUP INT TERM
target=$mount_dir/$relative
cmp "$project/uv.lock" "$target/uv.lock"
cmp "$project/pyproject.toml" "$target/pyproject.toml"
runuser -u "$user" -- env PROJECT_SYNC_DIR="$target" PROJECT_UV_BIN="$uv_bin" sh -c '
    cd "$PROJECT_SYNC_DIR"
    exec "$PROJECT_UV_BIN" sync --locked --group data --group dev --no-progress
'
