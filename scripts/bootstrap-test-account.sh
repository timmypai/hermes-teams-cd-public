#!/usr/bin/env bash
# Operator only, after exact-head review and successful read-only discovery.
set -euo pipefail
[[ $# == 0 ]] || { printf 'STOP no_parameters\n' >&2; exit 64; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$script_dir/readback-isolated-host.sh"
sb_identity; sb_policy; sb_storage
SB_STAGE=freshness
if getent passwd "$SB_USER" >/dev/null; then sb_stop existing_account_no_replay; fi
if getent group "$SB_USER" >/dev/null; then sb_stop existing_group; fi
sb_absent "$SB_HOME"; sb_absent /var/lib/sevenbot-deploy
[[ -z $(ss -H -ltn 'sport = :18080') ]] || sb_stop port_collision
sb_ranges /etc/subuid UID; [[ -z $SB_OWN_START ]] || sb_stop subordinate_name_collision
sub_uid=$SB_FREE_START
sb_ranges /etc/subgid GID; [[ -z $SB_OWN_START ]] || sb_stop subordinate_name_collision
sub_gid=$SB_FREE_START
SB_UID=${SB_POLICY[UID_MIN]}
while getent passwd "$SB_UID" >/dev/null || getent group "$SB_UID" >/dev/null; do
  SB_UID=$((SB_UID+1)); [[ $SB_UID -le ${SB_POLICY[UID_MAX]} ]] || sb_stop uid_exhausted
done
# No adoption of stale quota policy or a pre-existing unit for a recycled UID.
quota_rows=$(repquota --user --numeric "$SB_MOUNT")
while read -r owner rest; do [[ $owner != "#$SB_UID" ]] || sb_stop existing_uid_quota; done <<< "$quota_rows"
sb_home_mounts
sb_slice_fresh
sb_storage_enforcement
# All mutations below concern ONLY the new locked, keyless, nologin account.
# If a command fails after taking effect: preserve partial state; do not run again.
SB_STAGE=create_locked_account
useradd --uid "$SB_UID" --user-group --no-create-home --no-log-init --home-dir "$SB_HOME" --shell /usr/sbin/nologin --comment "$SB_MARK" --key SUB_UID_COUNT=0 --key SUB_GID_COUNT=0 "$SB_USER"
SB_STAGE=allocate_new_account_ids
usermod --add-subuids "$sub_uid-$((sub_uid+65535))" --add-subgids "$sub_gid-$((sub_gid+65535))" "$SB_USER"
SB_STAGE=set_new_account_quota
setquota --user "$SB_UID" 0 "$SB_BLOCKS" 0 "$SB_INODES" "$SB_MOUNT"
sb_quota
SB_STAGE=create_new_home
install -d -m 0700 -o "$SB_UID" -g "$SB_UID" "$SB_HOME"
SB_STAGE=configure_new_slice
install -d -m 0755 "/etc/systemd/system/user-$SB_UID.slice.d"
printf '[Slice]\nCPUQuota=100%%\nCPUQuotaPeriodSec=100ms\nMemoryMax=1073741824\nMemorySwapMax=0\nTasksMax=256\n' | install -m 0644 /dev/stdin "/etc/systemd/system/user-$SB_UID.slice.d/50-sevenbot.conf"
systemctl daemon-reload
SB_STAGE=start_new_user_manager
loginctl enable-linger "$SB_USER"
systemctl start "user@$SB_UID.service"
sb_account; sb_runtime
printf 'ACCOUNT_INITIALIZED schema=1 account=locked_nologin quota=hard aggregate_limits=kernel_verified daemon=NOT_CREATED runner=NOT_INSTALLED registration=HOLD\n'
