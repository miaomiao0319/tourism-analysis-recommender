#!/bin/sh
# Root starts a temporary metadata-enabled mount; daemons run as the named user.
set -eu
if [ "$(id -u)" -ne 0 ] || [ "$#" -ne 2 ]; then
    echo 'Usage: JAVA_HOME=... HADOOP_HOME=... sh scripts/hadoop-wsl.sh <user> <init|start|status|stop>' >&2
    exit 2
fi
user=$1
action=$2
case "$action" in init|start|status|stop) ;; *) exit 2 ;; esac
uid=$(id -u "$user")
gid=$(id -g "$user")
[ "$uid" -ne 0 ]
: "${JAVA_HOME:?Set JAVA_HOME}" "${HADOOP_HOME:?Set HADOOP_HOME}"
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
case "$project" in
    /mnt/c/*) relative=${project#/mnt/c/} ;;
    /mnt/tourism-workspace/*) relative=${project#/mnt/tourism-workspace/} ;;
    *) echo 'Project must be on the C drive mount.' >&2; exit 2 ;;
esac
mount_dir=/mnt/tourism-workspace
mkdir -p "$mount_dir"
if ! mountpoint -q "$mount_dir"; then
    [ -z "$(ls -A "$mount_dir")" ] || { echo 'Mount directory not empty.' >&2; exit 1; }
    mount -t drvfs C: "$mount_dir" -o "uid=$uid,gid=$gid,metadata"
fi
target=$mount_dir/$relative
cmp "$project/uv.lock" "$target/uv.lock"
cmp "$project/scripts/hadoop.py" "$target/scripts/hadoop.py"
runuser -u "$user" -- env PROJECT_WSL_DIR="$target" JAVA_HOME="$JAVA_HOME" HADOOP_HOME="$HADOOP_HOME" sh -c '
    cd "$PROJECT_WSL_DIR"
    exec sh scripts/hadoop.sh "$1"
' sh "$action"
