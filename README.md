# Reusable public CD

Public target: `timmypai/hermes-teams-cd-public`.
Source and CI are delivered through reviewed protected pull requests; this is not
an inert-only seed anymore. The publication-only route uses the fixed public
standard native ARM64 runner, qualified immutable base and exact approved app.
See `docs/shared-delivery.md` for helper pinning, protected admission, immutable
archive/provenance/native smoke evidence and remaining release gates.

Source review/CI is not an image build, deployment, runner installation or
production grant. Host ACTIVATION stays UNBOUND. No actual image publication is
claimed without protected Actions execution and independently verified artifacts.
Historical sanitized ancestry is in `docs/public-source-provenance.md`.
