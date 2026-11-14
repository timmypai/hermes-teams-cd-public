#!/usr/bin/env bash
# Root operator orchestrates fixed commands through the NEW limited user manager.
# Does not register/start an Actions runner or activate CD.
set -euo pipefail
[[ $# == 0 ]] || { printf 'STOP no_parameters\n' >&2; exit 64; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$script_dir/readback-isolated-host.sh"
sb_identity; sb_policy; sb_storage; sb_account; sb_runtime
sb_storage_enforcement
SB_STAGE=daemon_freshness
for path in "$SB_HOME/actions-runner" "$SB_HOME/.local/share/docker" "$SB_HOME/.config/systemd/user/docker.service" "$SB_HOME/.config/docker" "$SB_HOME/.docker" "/run/user/$SB_UID/docker.sock"; do sb_absent "$path"; done
[[ $(sb_user_command systemctl --user show docker.service -p LoadState --value) == not-found ]] || sb_stop existing_daemon_unit
[[ $(sb_user_command systemctl --user show sevenbot-bootstrap.service -p LoadState --value) == not-found ]] || sb_stop existing_bootstrap_unit
# Every payload runs as a service under user@UID, NOT under the operator's slice.
sb_limited_command() {
  sb_user_command systemd-run --user --wait --collect --pipe --unit=sevenbot-bootstrap --working-directory="$SB_HOME" "$@"
}
SB_STAGE=create_runner_directory
sb_limited_command /usr/bin/install -d -m 0700 "$SB_HOME/actions-runner"
SB_STAGE=download_official_runner
sb_limited_command /usr/bin/curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 --max-time 120 https://github.com/actions/runner/releases/download/v2.338.2/actions-runner-linux-arm64-2.338.2.tar.gz --output "$SB_HOME/actions-runner/runner.tar.gz"
SB_STAGE=verify_official_runner
printf '670adb2f268fe21dcbb58b3db0e0aa9d5b3bddfe2c651481336e561ff86de945  %s/actions-runner/runner.tar.gz\n' "$SB_HOME" | sha256sum --check --strict
SB_STAGE=extract_official_runner
sb_limited_command /usr/bin/tar --extract --gzip --file "$SB_HOME/actions-runner/runner.tar.gz" --directory "$SB_HOME/actions-runner" --no-same-owner
SB_STAGE=prepare_rootless_daemon
# Already-installed official tooling only. Never install Docker or host dependencies.
sb_limited_command dockerd-rootless-setuptool.sh install
sb_runtime; sb_daemon
printf 'DAEMON_PREPARED schema=1 runner_package=2.338.2-linux-arm64 package_sha256=670adb2f268fe21dcbb58b3db0e0aa9d5b3bddfe2c651481336e561ff86de945 registration=HOLD runner_started=no\n'
