# Public shared delivery interface

Source repository: `timmypai/hermes-teams-cd-public`. Fresh sanitized ancestry,
not private history. Consumers pin one separately frozen helper ancestor; its
literal SHA is `74cbd88e1f53d3832be3c4c6c5c8512a0be37249`. Helper/workflow SHAs are
distinct. All six reusable workflows must retrieve matching helper bytes,
including publication_build.py and docker/Dockerfile, from that pinned revision.

## Hosted CI

`reusable-ci.yml` admits only the named app/CD repositories and supported CI
events, retrieves exact source and runs the actual approved application suite.
`cd-ci.yml` runs the full current CD suite plus reusable app CI. The always-run
exact `ci` gate requires all mandatory jobs success. Hosted check/app association
is separately verified, not inferred from YAML or local fixtures.

## Publication-only native ARM64 route

`publish.yml` accepts ONLY source-sha. Its same-revision reusable workflow uses
standard public `ubuntu-24.04-arm`, a protected environment and noncancelling
service lock. No caller runner, command, path, ref, environment or secret selector.
Publication requires exact protected reviewed CD main, attempt1, exact workflow,
qualified distinct exact-head approval and Actions ci on approved head AND main.
The application is fixed at eb3c70b0b520a955a014ea883c137db604ec0492, checked against
current app main, independent approval/ci and the accepted server byte hash.
This binding does not set ACTIVATION or authorize Oracle/production Docker.

Only the standard hosted local daemon is used after runner/context/native checks.
The previously-qualified immutable official Python ARM64 base is prefetched;
fixed Dockerfile builds without build network/pip/shell or mutable tags. Native
image inspect plus real nonroot/read-only/resource-limited loopback smoke checks
/version exact source/schema/revision, /healthz true and the functional message.
The exact owned ephemeral candidate is cleaned up; conflicts/cleanup errors stop.
Image metadata alone is not functional verification or native runtime proof.

Immutable `image-{run}-{attempt}` contains image.tar, schema1 provenance.json and
separate native.json (base/platform/smoke/size mapping). No schema1 consumer change.
Archive capped at 256MiB before upload, seven-day retention, no registry/cache or
packages:write. Standard public compute is free per GitHub documentation; that
is NOT proof of artifact storage allowance. Before any dispatch the owner must
qualify actual free artifact storage/retention eligibility and current protections,
including the existing oracle-sevenbot-test environment. No automatic spending,
protection edits or metered overage is authorized. Actual archive size/digest,
upload/download and independent hash verification remain release evidence.

## Host operations remain UNBOUND

`health.yml`, `deploy.yml`, `rollback.yml`, `status.yml` keep their fixed isolated
ARM64 runner, protected environment and host activation/rootless/isolation guards.
All operations retain the existing noncancelling environment/service lock. No PR
self-hosted execution, inherited secrets or caller-selected execution targets.

Inputs: source-sha, artifact-run/artifact-attempt, revision flow-probe-v1/v2;
paired previous identity for deploy and previous/known identities for rollback.
Operation evidence is `operation-{run}-{attempt}`. Archive hash/image ID are not a
registry digest. Status requires exact API readback and <=300s UTC freshness.

Source/offline fixture PASS is NOT hosted build, artifact upload, deployment,
health, rollback, installed runner or Epic acceptance. Host storage installation
remains failclosed and ACTIVATION remains None. These host gaps do not block
independent publication source work. Real image acceptance still requires the
reviewed protected workflow to execute and provide actual native evidence.
