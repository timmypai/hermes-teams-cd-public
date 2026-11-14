# Public reusable delivery onboarding

1. Record native task/run, requirement version, owner, write scope, repository contract,
   exact source/dependency heads, non-goals, validation and real platform/time/cost limits.
   Use the existing Dispatcher and native board only; Actions is not a control plane.
2. This source target is `timmypai/hermes-teams-cd-public`. Application source remains
   `timmypai/hermes-teams`, with fixed pilot contract in the shipped config/schema.
   No application repository changes are made here. New targets need a named grant
   and reviewed binding before creation; thin configuration is not broad authority.
3. Select an immutable public workflow release. Each reusable consumer retrieves its
   separately frozen helper ancestor from the public target, never caller scripts.
   The literal helper pin is documented in [shared-delivery](shared-delivery.md).
   Never use a mutable branch/tag or caller-selected helper repository/ref.
4. Validate with `python3 shared/scripts/delivery.py validate --config
   shared/config/projects/sevenbot-flow-probe.json`. The strict stdlib validator and
   JSON Schema accept exactly the same named binding, reject duplicate/unknown fields
   and unsafe command/path/runner/target substitutions. No secret values belong here.
5. Public application CI is supported by the public reusable-ci workflow on standard
   hosted ubuntu-24.04 runners. It retrieves the pinned shared helper independently
   and executes the actual approved application unittest argv, not config-only tests.
   Consumers must pin the workflow release and preserve a caller-side exact always-run
   `ci` check that accepts only success of the complete reusable job. The existing
   application delivery is not retargeted or replayed by publishing this repository.
6. Operations are workflow_dispatch-only thin callers on protected reviewed public
   main, with read-only permissions and no inherited secrets. Privileged consumers
   must pass hosted admission before any isolated runner scheduling. Current trusted
   helper activation is UNBOUND; host security is DEFERRED/NOT_VERIFIED. Do not dispatch
   operations until the independently required protection, cost, identity, image and
   host gates are accepted. Public PRs never receive self-hosted execution.

Interface: exact 40-hex source-sha; artifact-run and artifact-attempt; closed revision
flow-probe-v1/flow-probe-v2; paired previous-run/previous-attempt and rollback known-run/
known-attempt. No arbitrary command/path/secret/environment/runner/repository selectors.
Publication takes only source-sha. Health takes source/artifact identity and revision.
See [acceptance](acceptance.md) and [host-initialization](host-initialization.md).
