#!/usr/bin/env bash
# PREPARED ONLY. Read-only host checks, no installation or service mutation.
set -euo pipefail
[[ $# == 0 ]] || { printf '%s\n' 'no parameters accepted' >&2; exit 64; }
[[ $(hostname -s) == dot-vm-a1 ]] || { printf '%s\n' 'wrong host' >&2; exit 1; }
[[ $(uname -m) == aarch64 ]] || { printf '%s\n' 'ARM64 required' >&2; exit 1; }
if getent passwd sevenbot-deploy >/dev/null; then
  printf '%s\n' 'existing account: inspect ownership out-of-band; STOP' >&2; exit 1
fi
for path in /home/sevenbot-deploy /var/lib/sevenbot-deploy; do
  [[ ! -e $path && ! -L $path ]] || { printf '%s\n' 'existing resource: STOP' >&2; exit 1; }
done
for executable in useradd getent ss curl sha256sum tar dockerd-rootless-setuptool.sh newuidmap newgidmap systemctl; do
  command -v "$executable" >/dev/null || { printf 'missing prerequisite: %s\n' "$executable" >&2; exit 1; }
done
[[ -f /sys/fs/cgroup/cgroup.controllers ]] || { printf '%s\n' 'cgroup v2 absent' >&2; exit 1; }
controllers=$(</sys/fs/cgroup/cgroup.controllers)
[[ " $controllers " == *' cpu '* && " $controllers " == *' memory '* && " $controllers " == *' pids '* ]] || exit 1
# Port must be unused by any family/address, not merely localhost.
[[ -z $(ss -H -ltn 'sport = :18080') ]] || { printf '%s\n' 'port conflict' >&2; exit 1; }
[[ -r /proc/sys/user/max_user_namespaces && $(</proc/sys/user/max_user_namespaces) -gt 0 ]] || exit 1
# Capacity check is evidence only; actual per-user enforcement remains mandatory.
available_kib=$(df -Pk /home | { read -r _; read -r _ _ _ available _; printf '%s' "$available"; })
[[ $available_kib =~ ^[0-9]+$ && $available_kib -ge 4194304 ]] || exit 1
printf '%s\n' 'PRECHECK_ONLY: host/architecture/name/paths/port/prerequisites/cgroup/capacity checked' \
  'NOT_INSTALLED: subuid/subgid allocation, user delegation, storage quota and runner isolation require readback'
