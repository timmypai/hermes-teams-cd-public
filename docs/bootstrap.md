# Host bootstrap — deferred, not a working installation

This public source distributes inert, failclosed preparation scripts. Source review
is not permission to execute them, install a runner, register an account or expose a
self-hosted runner to public PR code. The fixed pilot binding is dot-vm-a1/aarch64,
new sevenbot-deploy account, dedicated rootless Docker, sevenbot-isolated label,
oracle-sevenbot-test environment and loopback service port 18080. These are intended
bindings, not observed host facts or a new resource grant.

`bootstrap-test-account.sh` and `bootstrap-rootless-runner.sh` call the storage guard
before their first mutation. The guard emits exit78 with
`aggregate_storage_unenforced_subids_and_job_temporary_stores`. No operator argument,
environment variable or free-capacity receipt releases it. Do not offer either as a
working setup or run a known-blocked installer to consume an installation attempt.
See [host-initialization](host-initialization.md) for the unresolved constraint.

Dormant code pins the official ARM64 runner archive and verifies its checksum; this
is source wiring, not proof of a download or installed package. No registration/start
command is exposed. Any later runner registration must use the official secure host
channel without tokens in chat, inputs, configuration or receipts. A public target
requires separately reviewed public-runner security/eligibility and environment
protection. No PR job may use the isolated runner. Do not borrow production sockets,
retained containers or account credentials. No permissions, mounts, quotas, sudoers,
accounts, daemons, host packages or infrastructure changes belong to this phase.
