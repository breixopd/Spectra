# Compliance and Abuse Prevention Audit

## Product Boundary

- Spectra must be positioned and enforced as an authorized security assessment platform for infrastructure the customer owns or has explicit written permission to test.
- The product should not support anonymous offensive use. Require verified organization identity, named users, billing/contact records, and accountable audit trails before enabling autonomous or high-risk testing.
- Terms already require authorized testing, but product controls need to make this operational, not only contractual.

## Current Safeguards

- RBAC and role checks exist for mission, admin, tool, billing, and management surfaces.
- Audit logging exists for mission launch, tool management, auth/session actions, and admin operations.
- Tool execution includes deterministic scope validation support in `app.services.tools.scope_validator`.
- Human approval exists as a mission option (`requires_approval`) and there are safety/policy gates around higher-risk actions.
- Rate limit configuration exists for API, auth, tools, missions, and setup paths.
- Privacy policy includes GDPR legal basis, retention, user rights, automated analysis disclosure, and opt-in training data language.
- Mission creation now requires an explicit `authorization_confirmed` assertion and records it in the mission launch audit log.

## Gaps Before Company Release

- Scope proof is not yet strong enough. The new authorization assertion is a baseline gate, but users should prove domain/IP ownership or upload customer authorization before autonomous scans, external targets, exploitation, payload generation, or listener/file-server capabilities are enabled.
- Account trust tiering is missing. New accounts should start with conservative limits: passive recon only, low concurrency, no exploitation, no payload generation, no internet-wide CIDR scans, and no anonymous crypto-style signup path.
- Abuse detection needs explicit product logic: high failure rates against many unrelated targets, broad internet scanning, repeated external CIDRs, high-risk tools against unverified targets, and rapid tenant/user creation should trigger review or suspension.
- Mission persistence/recovery is a reliability and compliance issue. Running missions currently can disappear after app recreation; this weakens evidence trails and incident review. Mission lifecycle events must be durably stored early and marked interrupted on restart if not resumable.
- Export controls/sanctions screening are not documented. For a security testing SaaS, add at least business-country collection, denied-party/sanctioned-region policy, and admin review for high-risk jurisdictions.
- Legal docs need stronger authorized-use language for proof of authority, emergency suspension, disclosure cooperation, prohibited targets, and abuse reporting.
- Data processing paperwork is incomplete for enterprise use: DPA, subprocessors list, retention matrix, incident response SLA, security whitepaper, vulnerability disclosure policy, and SOC 2/ISO 27001 readiness docs are missing.
- Evidence retention should distinguish customer assessment data, abuse/security audit logs, billing/tax records, and AI training opt-in datasets.

## Recommended Guardrails

- Require target verification for public domains/IP ranges: DNS TXT, HTTP well-known token, cloud account integration, uploaded authorization letter, or admin-approved allowlist.
- Add a target ownership state machine: `unverified`, `verified_passive`, `verified_active`, `exploitation_allowed`, `expired`, `revoked`.
- Make high-risk tools require both verified target scope and explicit mission approval. Examples: credential attacks, exploitation frameworks, payload generation, reverse listeners, pivoting, and post-exploitation helpers.
- Add abuse-risk scoring per tenant and mission. Inputs: target diversity, public IP breadth, tool risk level, concurrency, account age, failed authorization checks, provider complaints, and manual reports.
- Add admin review queue for suspicious missions with full replay: user, tenant, target proof, command log, tool outputs, AI decisions, approvals, and network metadata.
- Enforce egress controls from tool containers: block prohibited destinations, restrict scans to mission scope, and log denied connection attempts.
- Add customer-facing authorization checklist at mission creation: “I own this target or have written permission”, testing window, point of contact, allowed techniques, excluded systems, and emergency stop contact.
- Add emergency kill switches per mission, user, tenant, target, and global provider incident.

## Compliance Roadmap

- Short term: strengthen Terms, add target authorization workflow, durable mission audit lifecycle, abuse-risk flags, and staff/admin review UI.
- Medium term: DPA/subprocessor docs, retention matrix, SOC 2 control mapping, vulnerability disclosure policy, incident response policy, and customer security page.
- Longer term: SOC 2 Type I/II or ISO 27001, annual third-party pentest, enterprise SSO/SCIM, regional data residency, and formal export-control/sanctions process.
