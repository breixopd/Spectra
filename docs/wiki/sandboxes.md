# Sandboxes

[Wiki Home](Home.md) · [Configuration](configuration.md) · [Security](security.md)

Spectra runs target-facing tool work in short-lived, per-mission containers. A
sandbox is an execution boundary, not a general-purpose application replica.

## Control plane

The scheduler is the only production service with Docker access. API replicas
use the scheduler's authenticated `/v1/sandboxes` control-plane API and never
remove containers on application startup or shutdown. This prevents an API
rollout from interrupting active work.

The scheduler reconciles only labelled resources that have no active sandbox
database record. It does not use blanket container cleanup. Stale creation
records are failed after five minutes; their credentials and Docker resources
are then eligible for reconciliation.

## Lifecycle

1. A mission requests a sandbox through the scheduler.
2. The scheduler records a `creating` sandbox, provisions a database role for
   that mission, then starts the container.
3. The worker consumes only that mission's `mission_<uuid-prefix>` queue.
4. Normal mission finalization or the watchdog destroys the container,
   revokes its database permissions, and removes its private egress network.

Container and network names include the full UUID (with separators removed),
avoiding the collision risk of short identifiers in long-lived deployments.

## Network and database isolation

Every sandbox has two networks:

- A per-mission bridge network provides target-facing egress.
- The deployment-owned `sandbox` network is internal and attaches only the
  sandbox and PostgreSQL. It is never the general backend network, so a tool
  container cannot reach Redis, internal APIs, or object storage directly.

Network isolation is mandatory. `SANDBOX_NETWORK_ISOLATION=false` is rejected
at configuration load, and the admin settings API does not expose that
boundary as a mutable switch.

The scheduler creates a random-password PostgreSQL login role per mission.
That role has only `SELECT` and `UPDATE` on `job_queue`; PostgreSQL row-level
security restricts it to its own queue. The primary platform database
credential is never passed to a sandbox. The database role used by the
scheduler must therefore be allowed to create and drop these ephemeral roles;
if it is not, sandbox creation fails closed and the mission uses the shared
worker path instead.

## Container hardening

- Read-only root filesystem with bounded `tmpfs` mounts for `/tmp`, `/var/tmp`,
  and transient `/app/data`.
- No Docker socket, application data volume, tool-binary volume, or mutable
  plugin volume is mounted into a sandbox.
- All Linux capabilities are dropped. VPN missions receive only `NET_ADMIN`,
  `NET_RAW`, and `/dev/net/tun`; raw networking is otherwise opt-in through
  `SANDBOX_ALLOW_RAW_NETWORK`.
- `no-new-privileges`, a PID limit of 256, no swap, and Docker's default seccomp
  profile apply to every container.

The approved plugin definitions are baked into the promoted worker image.
Runtime plugin volume sharing is intentionally not supported at this boundary.

## Operational checks

`GET /v1/sandboxes/health` is service-authenticated and reports scheduler
controller availability. Scheduler deep health and maintenance loops expose
task failure/recovery state; operational automation should alert on a degraded
scheduler rather than treating a container process as proof of control-plane
health.

Relevant deployment settings:

| Setting | Default | Meaning |
|---|---:|---|
| `SANDBOX_IMAGE` | `spectra-tools` | Promoted image used for new sandboxes |
| `SANDBOX_NETWORK` | `sandbox` | Internal PostgreSQL-only network |
| `SANDBOX_MAX_CONTAINERS` | `10` | Platform-wide capacity limit |
| `SANDBOX_PER_USER_LIMIT` | `3` | Per-user concurrent limit |
| `SANDBOX_MAX_LIFETIME` | `7200` | Maximum sandbox age in seconds |
| `SANDBOX_IDLE_TIMEOUT` | `600` | Watchdog idle timeout in seconds |
| `SANDBOX_ALLOW_RAW_NETWORK` | `false` | Allow `NET_RAW` outside VPN missions |
