# Changelog

All notable changes are documented here. Spectra uses CalVer release tags in
the form `YYYY.MM.DD[.patch]`; generated GitHub release notes include the
commit-level change list and published image references.

## Unreleased

### Security

- Refreshed the locked Python dependency set to remediated upstream releases
  and made the dependency audit fail closed without advisory exemptions.
- Added a unique JWT ID to access and refresh tokens so rapid logout/login
  cycles cannot revoke a newly issued token with the same second-level claims.
- Added full-history secret scanning and GitHub Actions security analysis to CI.
- Hardened release workflow permissions and artifact handling.
- Replaced two rejected inline-Python plugin checks with first-party worker
  executables. The metadata probe now accepts only recognized metadata hosts,
  and the GraphQL probe validates its URL, headers, and bounded operation set.

### Changed

- Made `main` the release-ready branch and documented `dev` plus isolated
  worktree development as the supported contribution flow.
- Hardened the agent execution runtime with stable process-independent task
  identities, bounded concurrency, per-task timeouts, cancellation-safe
  retries, dependency/deadlock propagation, and deterministic plan validation.
- Made mission lifecycle status and its finite-state machine reconcile through
  audited forced transitions, added `timed_out`, and persisted checkpoint
  authorization, scope, plan, and FSM history for safe resume.
- Made autoscaling and maintenance fail closed on stale or partial metrics,
  protect queue-backed workers from unsafe downscaling, and restrict Docker
  cleanup to Spectra-managed resources.
- Made sensitive mission memory tenant-safe, size-bounded, and fail closed when
  encryption is missing or corrupted; concurrent embedding initialization is
  now serialized.
- Added a gateway-backed LLM adapter for API deployments and kept an existing
  application factory authoritative when one is configured.
- Hardened Swarm scaling, scheduler leadership, durable mission controls, and
  managed maintenance cleanup so transient failures fail closed and recover
  without silently affecting unrelated Docker workloads.
- Tightened upload, provisioning, endpoint, backup, image-promotion, and VPN
  safety boundaries, with explicit production configuration and deployment
  readiness checks.
- Reworked the public landing page and application state surfaces for a more
  accessible, responsive experience with no-JavaScript and reduced-motion
  fallbacks.
- Rebuilt the API frontend stage on Node 22, added npm audit gates, and aligned
  Playwright's container browser image with the locked client version.
- Separated API liveness from platform readiness so UI verification does not
  need external AI providers, while deployment gates retain full readiness.
- Made Caddy use `/api/healthz` for upstream and container liveness, so a
  transient optional dependency cannot take a live API instance out of service.
- Made the anonymous `/api/health` default use the cheap, redacted public scope;
  explicit platform and readiness scopes remain available for operators.
- Removed the fixed backend Docker subnet so parallel worktrees receive
  collision-free networks, and fixed Caddy's default upstream to the Compose
  service alias instead of a checkout-specific container name.
- Fixed the vulnerable network target's healthcheck image dependency and made
  live-target harnesses honor `SPECTRA_CONTAINER_PREFIX` for isolated runs.
- Restored authenticated API documentation and help routes, with a responsive
  help surface that matches the authenticated application boundary.

### Added

- Added benchmark polling and state-based postcondition grading instead of
  treating mission submission as success, plus regression coverage for the
  expanded agent/runtime and scaling contracts.
- Added Hypothesis to the development test toolchain and expanded CI parity to
  use deterministic Compose environment files and isolated cleanup.
- Stable mission-finding identities, evidence bundles, and selected-finding
  report exports.
- Real browser acceptance coverage for authentication, desktop routing, and
  phone-width navigation.
- Workspace wheel and source-distribution assets on GitHub releases.
- A clean, isolated Docker integration path that starts all required services,
  initializes Garage, validates first-party worker binaries, and tears itself
  down after the test run.

### Testing

- Replaced incompatible synchronous ASGI test clients with async HTTPX
  transports, corrected SQLAlchemy test-result doubles, reset global JWT test
  state, and removed coroutine/resource warnings from the unit suite. Pytest
  now fails on unawaited coroutine and unraisable background-task warnings.
- Added regressions for Caddy liveness, parallel-worktree target subnets,
  TensorZero's test-only provider configuration, worker CLI entry points, and
  first-party plugin input boundaries.
- Added browser coverage for authenticated help/API docs and a same-second
  token uniqueness regression for logout followed by immediate re-login.
- Rebased the unit-coverage ratchet on the measured full-suite baseline: CI and
  release now enforce a 65% floor across every first-party package, with no
  source areas excluded from the gate.
- Final verification covers 3,965 Docker unit tests, full Compose service
  health, performance smoke, live API e2e, authenticated Playwright UI flows,
  strict dependency auditing, secret scanning, and workflow security checks.
