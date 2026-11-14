#!/usr/bin/env bash
# Fixed-target readback and shared assertions. No host mutations in this file.
set -euo pipefail
export LC_ALL=C
readonly SB_USER=sevenbot-deploy SB_HOME=/home/sevenbot-deploy
readonly SB_BLOCKS=3145728 SB_INODES=262144 SB_MARK=sevenbot-v1-isolated
SB_STAGE=entry
sb_stop() { printf 'STOP schema=1 stage=%s reason=%s retained=yes replay=no\n' "$SB_STAGE" "$1" >&2; exit 78; }
sb_err() { local result=$?; trap - ERR; printf 'STOP schema=1 stage=%s reason=command_failed exit=%s retained=yes replay=no\n' "$SB_STAGE" "$result" >&2; exit "$result"; }
trap sb_err ERR
sb_stat() { stat --format='%F:%u:%g:%a' -- "$1"; }
sb_absent() { if stat -- "$1" >/dev/null 2>&1; then sb_stop resource_collision; fi; }
sb_identity() {
  [[ $(id -u) == 0 ]] || sb_stop operator_root_required
  [[ $(hostname -s) == dot-vm-a1 ]] || sb_stop wrong_host
  [[ $(uname -m) == aarch64 ]] || sb_stop wrong_arch
  [[ $(readlink -e /home) == /home && $(sb_stat /home) == directory:0:0:755 ]] || sb_stop home_parent_unsafe
}
sb_policy() {
  local key value rest
  declare -gA SB_POLICY=()
  local policy_rows; policy_rows=$(cat /etc/login.defs) || sb_stop id_policy_unreadable
  while read -r key value rest; do
    case "$key" in UID_MIN|UID_MAX|SUB_UID_MIN|SUB_UID_MAX|SUB_UID_COUNT|SUB_GID_MIN|SUB_GID_MAX|SUB_GID_COUNT)
      [[ $value =~ ^[0-9]{1,9}$ && ! -v SB_POLICY[$key] ]] || sb_stop invalid_id_policy
      SB_POLICY[$key]=$((10#$value));;
    esac
  done <<< "$policy_rows"
  for key in UID_MIN UID_MAX SUB_UID_MIN SUB_UID_MAX SUB_UID_COUNT SUB_GID_MIN SUB_GID_MAX SUB_GID_COUNT; do
    [[ -v SB_POLICY[$key] ]] || sb_stop missing_id_policy
  done
  [[ ${SB_POLICY[UID_MIN]} -ge 1000 && ${SB_POLICY[UID_MAX]} -le 60000 && ${SB_POLICY[UID_MAX]} -ge ${SB_POLICY[UID_MIN]} && ${SB_POLICY[SUB_UID_COUNT]} == 65536 && ${SB_POLICY[SUB_GID_COUNT]} == 65536 ]] || sb_stop unsupported_id_policy
  for key in UID GID; do
    [[ ${SB_POLICY[SUB_${key}_MIN]} -ge 65536 && ${SB_POLICY[SUB_${key}_MAX]} -ge ${SB_POLICY[SUB_${key}_MIN]} && ${SB_POLICY[SUB_${key}_MAX]} -le 4294967294 ]] || sb_stop unsafe_subordinate_policy
  done
}
sb_ranges() {
  local file=$1 owner start count tail i j end primary_rows primary_id primary_name password rest
  local database=passwd
  [[ $2 == UID ]] || database=group
  primary_rows=$(getent "$database") || sb_stop primary_id_inventory_failed
  local -a primary_ids=()
  while IFS=: read -r primary_name password primary_id rest; do
    [[ $primary_id =~ ^[0-9]{1,10}$ ]] || sb_stop malformed_primary_id
    primary_ids+=("$((10#$primary_id))")
  done <<< "$primary_rows"
  declare -a starts=() ends=()
  SB_OWN_START= SB_OWN_COUNT=
  # Materialize read failure, rather than accepting an empty process substitution.
  local rows; rows=$(cat "$file") || sb_stop subordinate_file_unreadable
  while IFS=: read -r owner start count tail; do
    [[ -n $owner ]] || continue
    [[ -z $tail && $start =~ ^[0-9]{1,9}$ && $count =~ ^[0-9]{1,9}$ && $count -gt 0 ]] || sb_stop malformed_subordinate_range
    start=$((10#$start)); count=$((10#$count)); end=$((start+count-1))
    [[ $start -ge 65536 && $end -le 4294967294 ]] || sb_stop unsafe_subordinate_range
    for primary_id in "${primary_ids[@]}"; do
      [[ $primary_id -lt $start || $primary_id -gt $end ]] || sb_stop subordinate_primary_id_collision
    done
    for i in "${!starts[@]}"; do
      [[ $end -lt ${starts[i]} || $start -gt ${ends[i]} ]] || sb_stop overlapping_subordinate_ranges
    done
    starts+=("$start"); ends+=("$end")
    if [[ $owner == "$SB_USER" ]]; then
      [[ $start -ge ${SB_POLICY[SUB_${2}_MIN]} && $end -le ${SB_POLICY[SUB_${2}_MAX]} ]] || sb_stop own_subordinate_outside_policy
      [[ -z $SB_OWN_START ]] || sb_stop multiple_subordinate_allocations
      SB_OWN_START=$start; SB_OWN_COUNT=$count
    fi
  done <<< "$rows"
  local kind=$2 candidate=${SB_POLICY[SUB_${2}_MIN]} maximum=${SB_POLICY[SUB_${2}_MAX]} clash
  while :; do
    end=$((candidate+65535)); [[ $end -le $maximum ]] || sb_stop no_free_subordinate_range
    clash=0
    for primary_id in "${primary_ids[@]}"; do
      if [[ $primary_id -ge $candidate && $primary_id -le $end ]]; then candidate=$((primary_id+1)); clash=1; break; fi
    done
    [[ $clash == 0 ]] || continue
    for j in "${!starts[@]}"; do
      if [[ $end -ge ${starts[j]} && $candidate -le ${ends[j]} ]]; then candidate=$((ends[j]+1)); clash=1; break; fi
    done
    [[ $clash == 1 ]] || break
  done
  SB_FREE_START=$candidate
}
sb_storage() {
  SB_STAGE=storage
  local fs opts state
  fs=$(findmnt -n -o FSTYPE --target /home)
  opts=$(findmnt -n -o OPTIONS --target /home)
  # Support only existing active ext4 user quotas. Never enable quota/mount features.
  [[ $fs == ext4 && ,$opts, == *,usrquota,* ]] || sb_stop missing_existing_active_home_user_quota
  SB_MOUNT=$(findmnt -n -o TARGET --target /home)
  [[ $SB_MOUNT == / || $SB_MOUNT == /home ]] || sb_stop unsupported_home_mount
  state=$(quotaon --print-state --user "$SB_MOUNT") || sb_stop quota_state_unreadable
  [[ $state == *'user quota on '* && $state == *' is on' && $state != *$'\n'* ]] || sb_stop missing_existing_active_home_user_quota
  # Tools must already exist; this script installs nothing.
  local cmd
  for cmd in repquota setquota useradd usermod install loginctl systemctl runuser systemd-run curl tar sha256sum dockerd-rootless-setuptool.sh; do
    command -v "$cmd" >/dev/null || sb_stop missing_installed_prerequisite
  done
  printf 'READBACK schema=1 stage=storage filesystem=ext4 user_quota=active mount=%s candidate_uid_hard_kib=%s aggregate_storage=UNQUALIFIED mapped_subids=NOT_COVERED job_tmp=NOT_CONFINED mutation=none\n' "$SB_MOUNT" "$SB_BLOCKS"
}
sb_storage_enforcement() {
  # A UID quota charges files to their host UID, not the namespace's root UID.
  # Rootless layer files owned by subordinate IDs are therefore outside SB_UID's
  # quota. /tmp and /var/tmp are also not confined by a home quota or runtime cap.
  # Per-ID quotas summed independently cannot certify ONE total <=4GiB ceiling.
  # No permitted mechanism in this revision closes these holes. Do not create
  # the account, start a manager, download, or start Docker before resolving them.
  SB_STAGE=storage_enforcement
  sb_stop aggregate_storage_unenforced_subids_and_job_temporary_stores
}
sb_ancestors() {
  local path=$1 current=/ part
  [[ $path == /* && $path != *'/../'* && $path != *'/./'* ]] || sb_stop unsafe_path
  [[ $(readlink -e /) == / ]] || sb_stop ancestor_symlink
  local -a parts
  IFS=/ read -r -a parts <<< "${path#/}"
  for part in "${parts[@]}"; do
    [[ -n $part ]] || continue
    current=${current%/}/$part
    [[ $(readlink -e "$current") == "$current" ]] || sb_stop ancestor_symlink
  done
}
sb_home_mounts() {
  local rows target
  rows=$(findmnt -rn -o TARGET) || sb_stop mount_inventory_failed
  while IFS= read -r target; do
    [[ $target != "$SB_HOME" && $target != "$SB_HOME/"* ]] || sb_stop home_submount
  done <<< "$rows"
}
sb_slice_fresh() {
  local slice="user-$SB_UID.slice" prop value
  # Automatic implicit slices may be loaded without a fragment. LoadState alone
  # is neither ownership nor activity evidence. Never adopt any effective policy.
  sb_absent "/etc/systemd/system/$slice.d"
  for prop in FragmentPath DropInPaths ControlGroup; do
    value=$(systemctl show "$slice" -p "$prop" --value)
    [[ -z $value ]] || sb_stop existing_slice_effective_state
  done
  [[ $(systemctl show "$slice" -p ActiveState --value) == inactive && $(systemctl show "$slice" -p SubState --value) == dead ]] || sb_stop existing_slice_activity
  [[ $(systemctl show "$slice" -p MemoryMax --value) == infinity && $(systemctl show "$slice" -p MemorySwapMax --value) == infinity && $(systemctl show "$slice" -p CPUQuotaPerSecUSec --value) == infinity && $(systemctl show "$slice" -p TasksMax --value) == infinity ]] || sb_stop existing_slice_effective_limits
  sb_absent "/sys/fs/cgroup/user.slice/$slice"
  [[ $(systemctl show "user@$SB_UID.service" -p ActiveState --value) == inactive && -z $(systemctl show "user@$SB_UID.service" -p ControlGroup --value) ]] || sb_stop existing_manager
}
sb_quota() {
  local rows line name flags used soft hard grace iused isoft ihard extra found=0
  rows=$(repquota --user --numeric "$SB_MOUNT") || sb_stop quota_readback_failed
  while read -r name flags used soft hard grace iused isoft ihard extra; do
    [[ $name == "#$SB_UID" ]] || continue
    [[ $found == 0 ]] || sb_stop ambiguous_quota
    found=1
    # repquota omits the block grace column when no soft limit is exceeded.
    if [[ $grace =~ ^[0-9]+$ ]]; then ihard=$isoft; isoft=$iused; iused=$grace; fi
    [[ $flags == -- && $used =~ ^[0-9]+$ && $soft == 0 && $hard == "$SB_BLOCKS" && $ihard == "$SB_INODES" && $used -le $SB_BLOCKS ]] || sb_stop hard_quota_mismatch
  done <<< "$rows"
  [[ $found == 1 ]] || sb_stop missing_hard_quota
}
sb_account() {
  SB_STAGE=account
  local row name password uid gid gecos home shell
  row=$(getent passwd "$SB_USER") || sb_stop account_missing
  [[ $row != *$'\n'* ]] || sb_stop ambiguous_account
  IFS=: read -r name password uid gid gecos home shell <<< "$row"
  [[ $name == "$SB_USER" && $uid =~ ^[0-9]+$ && $uid -ge ${SB_POLICY[UID_MIN]} && $uid -le ${SB_POLICY[UID_MAX]} && $gid == "$uid" && $gecos == "$SB_MARK" && $home == "$SB_HOME" && $shell == /usr/sbin/nologin ]] || sb_stop foreign_account
  SB_UID=$uid
  sb_ancestors "$SB_HOME"; sb_home_mounts
  [[ $(getent group "$SB_USER") == "$SB_USER:x:$uid:" ]] || sb_stop foreign_group
  [[ $(readlink -e "$SB_HOME") == "$SB_HOME" && $(sb_stat "$SB_HOME") == "directory:$uid:$gid:700" ]] || sb_stop home_ownership_or_symlink
  sb_absent /var/lib/sevenbot-deploy
  sb_ranges /etc/subuid UID
  [[ $SB_OWN_COUNT == 65536 ]] || sb_stop subordinate_uid_missing
  sb_ranges /etc/subgid GID
  [[ $SB_OWN_COUNT == 65536 ]] || sb_stop subordinate_gid_missing
  sb_quota
  printf 'READBACK schema=1 stage=account uid=%s home=dedicated subordinate_ids=nonoverlapping quota=hard\n' "$SB_UID"
}
sb_runtime() {
  SB_STAGE=runtime
  local slice="user-$SB_UID.slice" delegate runtime_size runtime_fs control effective
  [[ $(systemctl show "$slice" -p MemoryMax --value) == 1073741824 && $(systemctl show "$slice" -p MemorySwapMax --value) == 0 && $(systemctl show "$slice" -p CPUQuotaPerSecUSec --value) == 1s && $(systemctl show "$slice" -p TasksMax --value) == 256 ]] || sb_stop aggregate_slice_limits_missing
  control=$(systemctl show "$slice" -p ControlGroup --value)
  [[ $control == "/user.slice/$slice" ]] || sb_stop wrong_slice_cgroup
  sb_ancestors "/sys/fs/cgroup$control"
  [[ $(cat "/sys/fs/cgroup$control/memory.max") == 1073741824 && $(cat "/sys/fs/cgroup$control/memory.swap.max") == 0 && $(cat "/sys/fs/cgroup$control/cpu.max") == '100000 100000' && $(cat "/sys/fs/cgroup$control/pids.max") == 256 ]] || sb_stop kernel_slice_limits_missing
  [[ $(systemctl show "user@$SB_UID.service" -p ControlGroup --value) == "$control/user@$SB_UID.service" ]] || sb_stop manager_outside_slice
  delegate=$(systemctl show "user@$SB_UID.service" -p Delegate --value)
  [[ $delegate == yes || ( " $delegate " == *' cpu '* && " $delegate " == *' memory '* && " $delegate " == *' pids '* ) ]] || sb_stop delegation_missing
  [[ $(sb_stat "/run/user/$SB_UID") == "directory:$SB_UID:$SB_UID:700" && $(readlink -e "/run/user/$SB_UID") == "/run/user/$SB_UID" ]] || sb_stop runtime_ownership_or_symlink
  sb_ancestors "/run/user/$SB_UID"
  [[ $(findmnt -n -o TARGET --target "/run/user/$SB_UID") == "/run/user/$SB_UID" ]] || sb_stop runtime_not_separate_mount
  runtime_fs=$(findmnt -n -o FSTYPE --target "/run/user/$SB_UID")
  runtime_size=$(findmnt -b -n -o SIZE --target "/run/user/$SB_UID")
  [[ $runtime_fs == tmpfs && $runtime_size =~ ^[0-9]+$ && $runtime_size -gt 0 && $runtime_size -le 1073741824 ]] || sb_stop runtime_storage_not_bounded
  printf 'READBACK schema=1 stage=runtime aggregate_cpu=1 aggregate_memory_bytes=1073741824 runtime_storage_bytes=%s delegation=present\n' "$runtime_size"
}
sb_user_command() {
  # Only internal fixed argv call sites; never accept commands from script arguments.
  runuser --user "$SB_USER" -- env -i HOME="$SB_HOME" USER="$SB_USER" LOGNAME="$SB_USER" XDG_RUNTIME_DIR="/run/user/$SB_UID" PATH=/usr/local/bin:/usr/bin:/bin "$@"
}
sb_daemon() {
  SB_STAGE=daemon
  local security root endpoint control
  sb_ancestors "$SB_HOME/.local/share/docker"; sb_home_mounts
  [[ $(sb_stat "/run/user/$SB_UID/docker.sock") == "socket:$SB_UID:$SB_UID:660" || $(sb_stat "/run/user/$SB_UID/docker.sock") == "socket:$SB_UID:$SB_UID:600" ]] || sb_stop wrong_socket
  [[ $(readlink -e "$SB_HOME/.local/share/docker") == "$SB_HOME/.local/share/docker" && $(stat --format='%u:%g' -- "$SB_HOME/.local/share/docker") == "$SB_UID:$SB_UID" ]] || sb_stop wrong_daemon_data
  [[ $(systemctl show "user@$SB_UID.service" -p Delegate --value) != no ]] || sb_stop delegation_missing
  # Explicit socket on EVERY Docker call; never ambient/default/production context.
  security=$(sb_user_command docker --host "unix:///run/user/$SB_UID/docker.sock" info --format '{{json .SecurityOptions}}')
  [[ $security == *'"name=rootless"'* ]] || sb_stop non_rootless_daemon
  root=$(sb_user_command docker --host "unix:///run/user/$SB_UID/docker.sock" info --format '{{.DockerRootDir}}')
  [[ $root == "$SB_HOME/.local/share/docker" ]] || sb_stop wrong_daemon_data
  endpoint=$(sb_user_command systemctl --user show docker.service -p ControlGroup --value)
  [[ $endpoint == "/user.slice/user-$SB_UID.slice/user@$SB_UID.service/"* ]] || sb_stop daemon_outside_slice
  printf 'READBACK schema=1 stage=daemon rootless=yes socket=dedicated data=dedicated registration=HOLD public_runner_security=NOT_VERIFIED runner_started=no\n'
}
sb_discover() {
  sb_identity; sb_policy; sb_storage
  sb_home_mounts
  sb_ranges /etc/subuid UID; [[ -z $SB_OWN_START ]] || sb_stop subordinate_name_collision
  printf 'READBACK schema=1 stage=subuid free_start=%s count=65536\n' "$SB_FREE_START"
  sb_ranges /etc/subgid GID; [[ -z $SB_OWN_START ]] || sb_stop subordinate_name_collision
  printf 'READBACK schema=1 stage=subgid free_start=%s count=65536\n' "$SB_FREE_START"
  printf 'READBACK schema=1 stage=discovery mutation=none account=NOT_CREATED runtime=NOT_QUALIFIED daemon=NOT_QUALIFIED registration=HOLD\n'
}
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  [[ $# == 1 ]] || sb_stop fixed_stage_required
  case "$1" in
    discover) sb_discover;;
    account|runtime|daemon)
      sb_identity; sb_policy; sb_storage; sb_account
      if [[ $1 != account ]]; then sb_runtime; fi
      if [[ $1 == daemon ]]; then sb_daemon; fi
      sb_storage_enforcement;;
    *) sb_stop unknown_stage;;
  esac
fi
