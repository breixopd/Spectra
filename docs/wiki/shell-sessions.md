# Shell Sessions Architecture

## Overview

Spectra provides interactive reverse shell sessions that connect through the
browser via WebSocket.  When an exploit establishes a reverse shell, the
platform bridges the raw TCP connection to a WebSocket so operators can
interact with the remote target from the web UI.

## Routing Modes

The `SHELL_ROUTING_MODE` setting controls **where** the TCP listener runs.

### `direct` (default)

The app container itself opens a TCP listener on ports 4444–4500.  Reverse
shells connect back to the app container's IP address.

- **Pros:** Simple, zero additional infrastructure.
- **Cons:** Exposes the app container's network address to targets.  The
  target sees the IP of the Spectra application server in connection logs,
  firewall rules, and PCAP captures.

### `sandbox`

The TCP listener runs **inside the mission's ephemeral sandbox container**.
Spectra uses Docker exec to launch `socat TCP-LISTEN:<port>,reuseaddr,fork STDIO`
inside the sandbox, then relays data between the exec socket and the
WebSocket.

- **Pros:** The target only sees the sandbox's IP, which is a throwaway
  container destroyed after the mission.  No link back to the app server.
  The sandbox already has `NET_RAW` and `NET_ADMIN` capabilities.
- **Cons:** Requires a running sandbox for the mission.  If no sandbox
  exists (e.g., sandbox pool disabled), automatically falls back to direct
  mode.

### `proxy` (future / placeholder)

Traffic will be routed through external proxy nodes — cheap VPS instances
that terminate the reverse shell and relay it back to Spectra over an
encrypted tunnel.

- Configure nodes via `SHELL_PROXY_NODES` (list of URLs).
- Not yet implemented; setting this mode falls back to `direct` with a
  warning.

## Configuration

### Environment / `.env`

```env
SHELL_ROUTING_MODE=sandbox          # direct | sandbox | proxy
SHELL_PROXY_NODES=[]                # future: ["https://proxy1.example.com"]
```

### Runtime Settings API

```http
POST /api/settings
{
  "shell_routing_mode": "sandbox"
}
```

The setting is stored in the database and takes effect for the **next**
shell listener that is created.  Existing sessions are not affected.

## IP Exposure Mitigations

| Concern | Direct | Sandbox | Proxy (future) |
|---------|--------|---------|----------------|
| Target sees app IP | Yes | No | No |
| Target sees cloud provider | Yes | Depends on Docker network | No (cheap VPS) |
| Session survives container destroy | N/A | No — session ends | Yes |
| Extra infrastructure | None | Sandbox pool | VPS nodes |

## How It Works (Sandbox Mode)

```
Browser ↔ WebSocket ↔ App Container ↔ Docker exec (socat) ↔ Sandbox Container ↔ TCP ↔ Target
```

1. `ShellSessionManager.start_listener()` detects `SHELL_ROUTING_MODE=sandbox`.
2. It looks up the running sandbox container for the mission (`spectra-sandbox-<id[:8]>`).
3. `container.exec_run("socat TCP-LISTEN:<port>,reuseaddr,fork STDIO", ...)` is
   called with `socket=True` to get a raw bidirectional socket.
4. A relay thread reads from the exec socket and calls `session.broadcast_output()`,
   which forwards to the connected WebSocket.
5. Writes from the WebSocket go to `session.write()`, which sends data to the
   exec socket's stdin.
6. When the shell disconnects or the sandbox is destroyed, the session cleans up.

## Future: Proxy Server Approach

Dedicated lightweight VPS nodes would run a relay daemon:

1. The app asks a proxy node to open a listener on a specific port.
2. The proxy relays traffic to the app over a persistent WebSocket or WireGuard tunnel.
3. The target only sees the proxy's IP, which is disposable and unrelated to
   the Spectra infrastructure.
4. Multiple proxy nodes can be configured for geographic distribution or
   redundancy via `SHELL_PROXY_NODES`.
