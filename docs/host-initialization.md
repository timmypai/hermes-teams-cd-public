# Host initialization — DEFERRED / NOT_VERIFIED

No working installation is delivered. Both installer entrypoints preserve the
failclosed pre-mutation storage guard, exit78:

`STOP schema=1 stage=storage_enforcement reason=aggregate_storage_unenforced_subids_and_job_temporary_stores retained=yes replay=no`

A primary-UID home quota excludes files owned by mapped subordinate UIDs in rootless
Docker. Runner/job writes to /tmp and /var/tmp are not confined by that quota or a
runtime tmpfs cap. Separate per-ID limits do not establish one aggregate <=4GiB hard
ceiling over Docker, runner, work and all job temporary stores. Changing TMPDIR is
not isolation. Free disk or a read-only receipt cannot waive the missing enforcement.
No replacement filesystem/mount/quota/permission architecture is adopted here.

The readback script offers fixed `discover`, `account`, `runtime` and `daemon` stages.
Discovery is observational; the other stages end at the same storage guard after
component observations. Component-positive fixtures are NOT overall host acceptance.
Additional validators cover automatic implicit slice activity/fragments/drop-ins,
effective and kernel swap/CPU/memory/pids, manager ancestry/delegation, ancestor
symlinks, home submounts, subordinate-ID policy/ranges and primary-ID collisions.
They are necessary, not sufficient. Aggregate intended limits remain <=1 CPU,
<=1GiB memory and <=4GiB total storage across the entire isolated execution scope.

Unknown resources and partial effects are preserved. Failures emit bounded nonsecret
STOP records with retained=yes/replay=no; no deletion, adoption or blind replay.
No host observation, SSH transport, installation, registration, daemon/account/mount/
quota change or public runner security qualification is established by local fixtures.
Only a separately admitted, implemented and independently reviewed mechanism covering
the aggregate constraint can progress the dependent host stage. Source and hosted CI
can progress independently without weakening that host gate.
