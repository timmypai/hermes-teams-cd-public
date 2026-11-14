# Public source provenance

This repository has independent Git ancestry, not a clone or fork of private history.
The sanitized source snapshot derives from task `t_a397d55a`, source Run137 and
independent diagnostic Run138, immutable source commit
`a238cea4f2b763db21411ecd656cf8cb9e36abbd`.
Those historical diagnostics do not approve this public version.

Public delivery is task `t_37b9cb9f`, initial author Run144. Only the explicitly
admitted workflow, configuration, helper, documentation, skill and test paths are
imported. No private report, session, credentials or old Git objects are imported.
The inert root contains only README, ignore rules and this provenance document.
A descendant freezes target-adapted helpers; subsequent consumers pin that real
ancestor. Exact root/helper/release identities belong in the delivery handoff and
can be inspected using ordinary Git history. Local tests are not hosted acceptance.

## Protected-main immutable helper version

The next helper is public protected-main commit
`61735e88d27170439de9e2210b9748f9bf68795f`, sole parent
`91240240eec95baa36ea03f5125800df5da40741`, reviewed source tree
`f1ef38f34e39791e4422bb55eb586e052b74d725`. Its seven implementation inputs
are byte/mode-identical to prior helper
`74cbd88e1f53d3832be3c4c6c5c8512a0be37249`; helper implementation is unchanged.
That earlier feature helper is not an ancestor of the protected squash, despite
matching implementation bytes. Its old independent approval does not approve
new consumers. Public inert seed and sanitized source ancestry are preserved.

Incremental consumers integrate the accepted main non-destructively and pin the
accepted helper explicitly. Both synthetic PR merge and production-style squash
must retain that helper in actual parent ancestry, bind all six repository/ref/env
pins and both documents, and match all seven helper inputs. Tests create real
local Git trees/commits with negative history, byte and pin substitutions. These
fixtures do not prove a hosted CI, protected merge or native ARM64 image result.
