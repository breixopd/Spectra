# UI Audit: Missions, Manual Tools, Reports

Status: loop 1 draft
Scope: dashboard mission launch, manual tools, toolbox, shell/session UI, findings, reports, history.

## What Looks Good

- Mission launch now includes an explicit authorization confirmation, which is important for abuse prevention.
- Manual tools, toolbox, and reports each have dedicated templates and JS modules.
- Existing tests cover basic dashboard rendering, mission launch form visibility, manual-mode entitlement redirect, toolbox page, reports page, and several role restrictions.

## Findings

- Mission actions need a clearer state machine in the UI. Launch, pause, stop, steering, shell sessions, finding validation, report generation, and evidence downloads should each expose loading, success, failure, blocked, and permission-denied states.
- Dashboard markup is large and combines mission launch, onboarding, map, findings, sessions, graph, logs, and agents in one template. It should be split into reusable partials/macros.
- Manual tools and toolbox overlap conceptually. Product IA should clearly distinguish "operator workspace" from "admin/tool registry" and use consistent capability gating.
- Finding evidence requirements need to be visible in report/finding UI. High/critical findings should show reproducibility evidence, artifact hash, scope target, and validation status.
- Live mission tests against vulnerable containers are not yet part of the normal verified path. They should be explicit, isolated, rate-limit aware, and safe to run only against known Docker target networks.

## Recommended Work

- Split dashboard into partials:
  - mission launch bar
  - mission status/progress
  - findings summary
  - topology graph
  - activity timeline
  - agent cards
  - session list
  - onboarding/empty state
- Add a mission UI state model shared between JS modules and tests.
- Add "blocked by policy" UI states with clear reasons and recovery actions:
  - plan upgrade
  - request access
  - out-of-scope target
  - processing restricted
  - unsafe target
  - worker unavailable
- Add Playwright flows for:
  - free plan cannot launch restricted mission type and sees upgrade path.
  - professional/enterprise can launch allowed mission.
  - processing-restricted user cannot launch and sees GDPR explanation.
  - staff can view allowed data but cannot launch.
  - report generation with and without advanced reporting.
  - artifact/evidence download entitlement and ownership checks.

## Live Mission Test Plan

- Use only Docker vulnerable targets on the `targets` network.
- Ensure only worker/tools containers contact targets.
- Run quick recon first, then a bounded web-only profile.
- Record artifacts and assert report/finding evidence exists.
- Treat OpenRouter/provider 429 as an external skip only when the platform still handles it gracefully.

## Verification Targets

- No API/app/server container connects directly to target containers.
- Mission UI tests verify both visible state and API-side denial.
- Every high-risk action has an audit event and visible user-facing reason when denied.
