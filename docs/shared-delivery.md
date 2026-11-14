# Public shared delivery interface

Source repository: `timmypai/hermes-teams-cd-public`. This public distribution has
fresh sanitized ancestry, not old private history. The public workflow release pins
one separate immutable helper ancestor,
`4d92b63e419eb4a1db5ccf28b1d06779a53a55ac`, matching the literal HELPER_SHA in all six
reusable workflows. A release's helper SHA and workflow SHA are distinct identities. Later helper
changes require a new frozen helper ancestor and deliberate repinning of all consumers
and distribution documentation. No self-referential or unreachable private helper pin
is valid. Caller checkout and helper checkout are separate directories.

## Hosted CI

`reusable-ci.yml` admits only the named application or public CD repository and supported
CI events. It checks out shared helpers from the pinned public ancestor, validates
context/source input, retrieves exact application source and runs the approved actual
application unittest suite. Evidence records helper/source/run/attempt and true exit.
`cd-ci.yml` runs the complete current CD safety suite and the reusable application CI.
Its always-run exact `ci` gate accepts only success of ALL mandatory jobs. Failure,
cancellation, skipped, missing or injected result strings fail closed. Actual hosted
check name and Actions-app association remain acceptance evidence, not YAML inference.

## Protected operations (not activated)

`publish.yml`, `health.yml`, `deploy.yml`, `rollback.yml` and `status.yml` are thin
workflow_dispatch callers. Relative reusable references resolve at the same reviewed
caller revision. Public protected main/attempt1 and exact named caller workflow are
required. Hosted admission fails UNBOUND before an isolated runner is scheduled.
All privileged consumers share one noncancelling environment/service concurrency lock,
fixed protected environment and fixed isolated ARM64 runner. No caller selects a shell,
repository, environment, runner, helper ref or secret. No secrets are inherited.

Inputs: source-sha; artifact-run/artifact-attempt; revision flow-probe-v1/flow-probe-v2;
optional paired previous-run/previous-attempt for deploy; previous and known-run/
known-attempt required for rollback. Publication accepts source-sha only; health accepts
source/artifact identity and revision. Image artifacts are `image-{run}-{attempt}`
with image.tar/provenance.json. Operation evidence is `operation-{run}-{attempt}`.
Archive SHA256 and image ID are not claims of registry digest. No mutable latest.
Status reads fixed container/loopback endpoints; exact API readback and <=300s UTC
freshness are separate requirements. Download time is not collection time.

No qualified Dockerfile/base/native ARM64 image, installed runner, live artifact upload,
deployment, health, rollback or status is established. Activation remains None. Host
aggregate storage remains unenforced and installation failclosed. These stages do not
block independent public source/hosted CI, nor does source CI qualify them.
