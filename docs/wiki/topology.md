# System Topology

[← Wiki Home](home.md) | [Architecture](architecture.md) | [Microservices](microservices-split.md) | [Scaling](scaling.md)

---

Visual guide to Spectra's service topology, communication patterns, data flows, and scaling architecture.

---

## 1. Single-Node Topology

All services on a single Docker Compose host with one bridge network.

```mermaid
graph TB
    subgraph Internet
        User([User / Browser])
    end

    subgraph Host["Single Host (Docker Compose)"]
        subgraph Edge["Reverse Proxy"]
            Caddy["Caddy<br/>:80 / :443"]
        end

        subgraph AppLayer["Application Services"]
            App["App (Core API)<br/>:5000<br/>SERVICE_MODE=api"]
            AI["AI Service<br/>:5010<br/>SERVICE_MODE=ai"]
            Scheduler["Scheduler<br/>:5011<br/>SERVICE_MODE=scheduler"]
            Worker["Worker<br/>:5012<br/>SERVICE_MODE=worker"]
        end

        subgraph AIStack["AI Routing"]
            TZ["TensorZero Gateway<br/>:3000"]
        end

        subgraph DataLayer["Data Services"]
            PG["PostgreSQL 16<br/>pgvector<br/>:5432"]
            Redis["Redis 7<br/>:6379"]
            Garage["Garage S3<br/>:3900 / :3903"]
            CH["ClickHouse<br/>:8123"]
        end
    end

    subgraph External["External"]
        LLM["LLM Provider<br/>(OpenAI / OpenRouter)"]
    end

    User -->|HTTPS| Caddy
    Caddy -->|HTTP| App
    Caddy -->|HTTP| AI

    App -->|HTTP + Service Auth| AI
    App -->|SQL + pgvector| PG
    App -->|Rate limits| Redis
    App -->|S3 API| Garage
    App -->|PG INSERT job_queue| PG

    AI -->|HTTP| TZ
    AI -->|SQL + pgvector| PG
    TZ -->|HTTP| CH
    TZ -->|HTTPS| LLM
    TZ -->|HTTPS| LLM

    Scheduler -->|SQL| PG
    Scheduler -->|Docker socket| Worker

    Worker -->|SQL + SKIP LOCKED| PG
    Worker -->|S3 API| Garage
    Worker -->|Docker socket| Host

    PG -.->|NOTIFY/LISTEN| App
    PG -.->|NOTIFY/LISTEN| Worker
    PG -.->|NOTIFY/LISTEN| Scheduler

    classDef proxy fill:#f9a825,stroke:#f57f17,color:#000
    classDef app fill:#42a5f5,stroke:#1565c0,color:#fff
    classDef data fill:#66bb6a,stroke:#2e7d32,color:#fff
    classDef ai fill:#ab47bc,stroke:#6a1b9a,color:#fff
    classDef external fill:#ef5350,stroke:#b71c1c,color:#fff
    classDef user fill:#78909c,stroke:#37474f,color:#fff

    class Caddy proxy
    class App,Scheduler,Worker app
    class AI,TZ ai
    class PG,Redis,Garage,CH data
    class LLM external
    class User user
```

### Port Summary

| Service | Internal Port | Host Binding | Protocol |
|---------|--------------|--------------|----------|
| Caddy | 80 / 443 | `${SPECTRA_PORT}` / `${SPECTRA_HTTPS_PORT}` | HTTP/HTTPS |
| App | 5000 | — (via Caddy) | HTTP |
| AI Service | 5010 | — (via Caddy) | HTTP |
| Scheduler | 5011 | — (health only) | HTTP |
| Worker | 5012 | — (health only) | HTTP |
| PostgreSQL | 5432 | — (internal) | TCP |
| Redis | 6379 | — (internal) | TCP |
| Garage | 3900 / 3903 | 127.0.0.1 only | HTTP |
| TensorZero | 3000 | — (internal) | HTTP |
| ClickHouse | 8123 | — (internal) | HTTP |

---

## 2. Multi-Node Production Topology

A horizontally scaled deployment across dedicated node roles using Docker Swarm.

```mermaid
graph TB
    subgraph Internet
        Users([Users])
    end

    subgraph EdgeNode["Edge Node"]
        CaddyLB["Caddy LB<br/>TLS Termination<br/>:443"]
    end

    subgraph AppNodes["App Nodes (scalable)"]
        App1["App Replica 1<br/>:5000"]
        App2["App Replica 2<br/>:5000"]
        AI1["AI Service 1<br/>:5010"]
        AI2["AI Service 2<br/>:5010"]
    end

    subgraph SchedulerNode["Scheduler Node (single)"]
        Sched["Scheduler<br/>:5011<br/>Leader election"]
    end

    subgraph WorkerNodes["Worker Nodes (scalable)"]
        W1["Worker 1<br/>:5012"]
        W2["Worker 2<br/>:5012"]
        W3["Worker 3<br/>:5012"]
    end

    subgraph AIGateway["AI Gateway"]
        TZ["TensorZero<br/>:3000"]
    end

    subgraph DataNode["Data Node"]
        PG["PostgreSQL 16<br/>pgvector"]
        Redis["Redis 7"]
        Garage["Garage S3"]
        CH["ClickHouse"]
    end

    subgraph External
        LLM["LLM Provider"]
    end

    Users -->|HTTPS| CaddyLB
    CaddyLB -->|Round-robin| App1
    CaddyLB -->|Round-robin| App2

    App1 & App2 -->|Service Auth| AI1
    App1 & App2 -->|Service Auth| AI2
    App1 & App2 -->|SQL| PG
    App1 & App2 -->|Rate limits| Redis
    App1 & App2 -->|S3| Garage

    AI1 & AI2 -->|HTTP| TZ
    AI1 & AI2 -->|pgvector| PG
    TZ -->|Inference logs| CH
    TZ -->|API| LLM

    Sched -->|SQL| PG
    Sched -->|Docker API| WorkerNodes

    W1 & W2 & W3 -->|SKIP LOCKED| PG
    W1 & W2 & W3 -->|S3| Garage

    PG -.->|NOTIFY| App1 & App2
    PG -.->|NOTIFY| W1 & W2 & W3
    PG -.->|NOTIFY| Sched

    classDef edge fill:#f9a825,stroke:#f57f17,color:#000
    classDef app fill:#42a5f5,stroke:#1565c0,color:#fff
    classDef worker fill:#26a69a,stroke:#00796b,color:#fff
    classDef scheduler fill:#ffa726,stroke:#e65100,color:#000
    classDef data fill:#66bb6a,stroke:#2e7d32,color:#fff
    classDef ai fill:#ab47bc,stroke:#6a1b9a,color:#fff
    classDef external fill:#ef5350,stroke:#b71c1c,color:#fff

    class CaddyLB edge
    class App1,App2 app
    class W1,W2,W3 worker
    class Sched scheduler
    class AI1,AI2,TZ ai
    class PG,Redis,Garage,CH data
    class LLM external
```

### Node Roles

| Role | Services | Scaling | Notes |
|------|----------|---------|-------|
| **Edge** | Caddy | 1 (or external LB) | TLS termination, security headers |
| **App** | App + AI Service | Horizontal | Stateless; Docker DNS round-robin |
| **Scheduler** | Scheduler | 1 only | Duplicate schedulers cause double-runs |
| **Worker** | Worker | Horizontal | `SKIP LOCKED` distributes jobs safely |
| **Data** | PG, Redis, Garage, CH | Vertical / managed | Use managed DB for HA |

---

## 3. Communication Flows

### Mission Execution Flow

```mermaid
sequenceDiagram
    actor User
    participant Caddy
    participant App as App (API)
    participant PG as PostgreSQL
    participant Worker
    participant Sandbox as Sandbox Container
    participant Tool as Security Tool
    participant AI as AI Service
    participant WS as WebSocket

    User->>Caddy: POST /api/missions (HTTPS)
    Caddy->>App: Forward request
    App->>PG: INSERT mission + job_queue
    App->>User: 202 Accepted (mission_id)
    App->>WS: mission_created event

    PG-->>Worker: NOTIFY spectra_jobs_mission_{id}
    Worker->>PG: SELECT ... FOR UPDATE SKIP LOCKED
    Worker->>AI: Plan mission (agents)
    AI-->>Worker: Mission plan

    loop For each task in plan
        Worker->>Sandbox: Create container
        Sandbox->>Tool: Execute (nmap, nuclei, etc.)
        Tool-->>Sandbox: stdout/stderr
        Sandbox-->>Worker: Tool output
        Worker->>PG: INSERT findings
        Worker->>PG: UPDATE job status
        PG-->>App: NOTIFY tool_execution_completed
        App-->>WS: Push results to client
        WS-->>User: Real-time updates
    end

    Worker->>PG: Mission complete
    PG-->>App: NOTIFY mission_completed
    App-->>WS: Mission finished
    WS-->>User: Final results
```

### Auto-Scaling Flow

```mermaid
sequenceDiagram
    participant Sched as Scheduler
    participant PG as PostgreSQL
    participant AS as AutoScaler
    participant Docker as Docker API
    participant Workers as Worker Replicas

    loop Every capacity_check interval
        Sched->>PG: Query queue_depth, worker utilization
        PG-->>Sched: Metrics (depth=15, util=90%)

        Sched->>AS: evaluate(metrics)
        AS->>AS: Check policy thresholds

        alt Queue depth > scale_up_threshold
            AS-->>Sched: ScalingDecision(scale_up, 2→4)
            Sched->>Docker: docker service scale spectra_worker=4
            Docker-->>Workers: Spawn new replicas
            Docker-->>Sched: Success
        else Queue idle > idle_timeout
            AS-->>Sched: ScalingDecision(scale_down, 4→2)
            Sched->>Docker: docker service scale spectra_worker=2
            Docker-->>Workers: Remove excess replicas
        else Within thresholds
            AS-->>Sched: ScalingDecision(none)
        end
    end
```

---

## 4. Data Flow Diagram

```mermaid
flowchart LR
    subgraph UserLayer["User Layer"]
        Browser["Browser"]
    end

    subgraph EdgeLayer["Edge"]
        Caddy["Caddy<br/>TLS + Headers"]
    end

    subgraph APILayer["API Layer"]
        App["App Service"]
        AI["AI Service"]
    end

    subgraph QueueLayer["Job Queue"]
        PGQ["PostgreSQL<br/>job_queue table"]
    end

    subgraph ExecutionLayer["Execution"]
        Worker["Worker"]
        Sandbox["Sandbox Containers"]
    end

    subgraph StorageLayer["Storage"]
        PG["PostgreSQL<br/>Missions, Users,<br/>Findings, RAG"]
        S3["Garage S3<br/>Artifacts, Backups,<br/>Sessions, Knowledge"]
        Redis["Redis<br/>Rate Limits,<br/>Session Cache"]
    end

    subgraph AILayer["AI Pipeline"]
        RAG["pgvector<br/>RAG Index"]
        TZ["TensorZero"]
        CH["ClickHouse<br/>Inference Logs"]
        LLM["LLM Provider"]
    end

    Browser -->|"Requests"| Caddy
    Caddy -->|"API calls"| App
    App -->|"Mission data"| PG
    App -->|"Enqueue jobs"| PGQ
    App -->|"Rate checks"| Redis
    App -->|"AI requests"| AI

    PGQ -->|"NOTIFY"| Worker
    Worker -->|"Execute tools"| Sandbox
    Sandbox -->|"Results"| Worker
    Worker -->|"Findings"| PG
    Worker -->|"Scan artifacts"| S3

    AI -->|"Embeddings query"| RAG
    RAG ---|"pgvector cosine"| PG
    AI -->|"LLM routing"| TZ
    TZ -->|"Inference"| LLM
    TZ -->|"Logs"| CH

    App -->|"Backups"| S3
    App -->|"WebSocket"| Browser

    classDef user fill:#78909c,stroke:#37474f,color:#fff
    classDef edge fill:#f9a825,stroke:#f57f17,color:#000
    classDef api fill:#42a5f5,stroke:#1565c0,color:#fff
    classDef queue fill:#ffa726,stroke:#e65100,color:#000
    classDef exec fill:#26a69a,stroke:#00796b,color:#fff
    classDef store fill:#66bb6a,stroke:#2e7d32,color:#fff
    classDef ai fill:#ab47bc,stroke:#6a1b9a,color:#fff

    class Browser user
    class Caddy edge
    class App,AI api
    class PGQ queue
    class Worker,Sandbox exec
    class PG,S3,Redis store
    class RAG,TZ,CH,LLM ai
```

### Data Stores Summary

| Store | Data | Access Pattern |
|-------|------|---------------|
| **PostgreSQL** | Users, missions, findings, job queue, RAG vectors, audit logs | OLTP + pgvector HNSW |
| **Garage (S3)** | Scan artifacts, backups, pentest sessions, knowledge docs | Object PUT/GET |
| **Redis** | Rate limit counters, distributed locks | Key-value, TTL-based |
| **ClickHouse** | TensorZero inference logs, AI analytics | Columnar append |

---

## 5. Service Dependencies

### Startup Order

Services must start in dependency order. Docker Compose enforces this via `depends_on` with health checks.

```mermaid
graph TB
    PG["PostgreSQL"] --> App
    PG --> AI["AI Service"]
    PG --> Scheduler
    PG --> Worker

    Redis --> App

    Garage --> App
    Garage --> Scheduler
    Garage --> Worker

    CH["ClickHouse"] --> TZ["TensorZero"]
    TZ --> AI
    TZ --> App

    AI --> App

    App --> Caddy

    classDef infra fill:#66bb6a,stroke:#2e7d32,color:#fff
    classDef service fill:#42a5f5,stroke:#1565c0,color:#fff
    classDef edge fill:#f9a825,stroke:#f57f17,color:#000

    class PG,Redis,Garage,CH infra
    class App,AI,Scheduler,Worker,TZ service
    class Caddy edge
```

### Startup Dependency Table

| Service | Depends On | Health Check |
|---------|-----------|--------------|
| **PostgreSQL** | — | `pg_isready -U spectra` |
| **Redis** | — | `redis-cli ping` |
| **Garage** | — | `/garage status` |
| **ClickHouse** | — | `clickhouse-client --query "SELECT 1"` |
| **TensorZero** | ClickHouse | `wget http://localhost:3000/health` |
| **AI Service** | PostgreSQL, TensorZero | `curl http://localhost:5010/health` |
| **App** | PostgreSQL, Redis, Garage, AI Service, TensorZero | `curl http://localhost:5000/api/health` |
| **Scheduler** | PostgreSQL | `curl http://localhost:5011/health` |
| **Worker** | PostgreSQL | `curl http://localhost:5012/health` |
| **Caddy** | App | `wget http://localhost:80` |

### Graceful Shutdown Order

Reverse of startup — drain traffic before stopping backends:

1. **Caddy** — stop accepting new connections, drain in-flight requests
2. **App** — close WebSocket connections, stop API handlers
3. **Scheduler** — cancel background task loops
4. **Worker** — finish in-progress jobs (or re-queue), destroy sandbox containers
5. **AI Service** — drain pending LLM requests
6. **TensorZero** — flush inference logs to ClickHouse
7. **Redis** — persist AOF
8. **Garage** — flush pending writes
9. **ClickHouse** — flush buffers
10. **PostgreSQL** — checkpoint and shutdown

---

## 6. Auto-Scaling Architecture

The reactive scaling loop runs inside the Scheduler service via the `AutoScaler` engine.

```mermaid
flowchart TB
    subgraph Scheduler["Scheduler Service"]
        CM["Capacity Monitor<br/>(periodic loop)"]
        AS["AutoScaler Engine"]
    end

    subgraph Metrics["Metrics Sources"]
        PGQ["PostgreSQL<br/>queue_depth"]
        Docker["Docker API<br/>replica count"]
        Util["CPU / Connection<br/>utilization"]
    end

    subgraph Policies["Scaling Policies"]
        WP["Worker Policy<br/>min=1, max=10<br/>queue threshold=10"]
        AP["API Policy<br/>min=1, max=5<br/>util threshold=85%"]
        AIP["AI Policy<br/>min=1, max=3"]
    end

    subgraph Actions["Actions"]
        SU["Scale UP<br/>+1..N replicas"]
        SD["Scale DOWN<br/>-1 replica"]
        CD["Cooldown<br/>300s between actions"]
    end

    subgraph Swarm["Docker Swarm / Compose"]
        WR["Worker Replicas"]
        AR["API Replicas"]
        AIR["AI Service Replicas"]
    end

    CM -->|"Collect"| PGQ
    CM -->|"Collect"| Docker
    CM -->|"Collect"| Util
    CM -->|"Evaluate"| AS

    AS -->|"Apply"| WP
    AS -->|"Apply"| AP
    AS -->|"Apply"| AIP

    WP & AP & AIP -->|"Decision"| SU
    WP & AP & AIP -->|"Decision"| SD
    WP & AP & AIP -->|"Enforce"| CD

    SU -->|"docker service scale"| WR
    SU -->|"docker service scale"| AR
    SU -->|"docker service scale"| AIR
    SD -->|"docker service scale"| WR
    SD -->|"docker service scale"| AR
    SD -->|"docker service scale"| AIR

    classDef sched fill:#ffa726,stroke:#e65100,color:#000
    classDef metric fill:#78909c,stroke:#37474f,color:#fff
    classDef policy fill:#ab47bc,stroke:#6a1b9a,color:#fff
    classDef action fill:#42a5f5,stroke:#1565c0,color:#fff
    classDef infra fill:#66bb6a,stroke:#2e7d32,color:#fff

    class CM,AS sched
    class PGQ,Docker,Util metric
    class WP,AP,AIP policy
    class SU,SD,CD action
    class WR,AR,AIR infra
```

### Scaling Thresholds

| Service | Min | Max | Scale-Up Trigger | Scale-Down Trigger | Cooldown |
|---------|-----|-----|-----------------|-------------------|----------|
| **Worker** | 1 | 10 | Queue depth > 10 | Queue idle > 300s | 300s |
| **API** | 1 | 5 | Utilization > 85% | Utilization < 20% | 300s |
| **AI Service** | 1 | 3 | Utilization > 80% | Utilization < 20% | 300s |
| **Scheduler** | 1 | 1 | — (never scaled) | — | — |

### Scaling Formula (Workers)

```
desired = min(current + max(1, queue_depth ÷ threshold), max_replicas)
```

Workers scale proportionally to queue backlog. A queue depth of 30 with threshold 10 adds 3 replicas in one step.

---

## 7. Network Architecture

All services share a single Docker bridge network in Compose. Swarm deployments use an overlay network.

```mermaid
graph TB
    subgraph HostNetwork["Host Network"]
        HostPorts["Host Ports<br/>:80, :443 (Caddy)<br/>:3900, :3903 (Garage, localhost only)"]
    end

    subgraph SpectraNet["spectra-network (bridge)"]
        subgraph ProxyTier["Proxy Tier"]
            Caddy["Caddy"]
        end

        subgraph AppTier["Application Tier"]
            App["App :5000"]
            AI["AI Service :5010"]
            Scheduler["Scheduler :5011"]
            Worker["Worker :5012"]
            TZ["TensorZero :3000"]
        end

        subgraph DataTier["Data Tier"]
            PG["PostgreSQL :5432"]
            Redis["Redis :6379"]
            Garage["Garage :3900"]
            CH["ClickHouse :8123"]
        end
    end

    subgraph DockerSocket["Docker Socket (mount)"]
        Sock["/var/run/docker.sock"]
    end

    HostPorts ---|"port mapping"| Caddy
    HostPorts ---|"127.0.0.1 only"| Garage

    Caddy ---|"internal DNS"| App
    Caddy ---|"internal DNS"| AI

    App --- PG
    App --- Redis
    App --- Garage
    App --- AI
    App --- TZ

    AI --- PG
    AI --- TZ
    TZ --- CH

    Scheduler --- PG
    Worker --- PG
    Worker --- Garage

    Worker -.-|"mount"| Sock
    App -.-|"read-only mount"| Sock
    Scheduler -.-|"read-only mount"| Sock

    classDef host fill:#78909c,stroke:#37474f,color:#fff
    classDef net fill:#e3f2fd,stroke:#1565c0,color:#000
    classDef proxy fill:#f9a825,stroke:#f57f17,color:#000
    classDef app fill:#42a5f5,stroke:#1565c0,color:#fff
    classDef data fill:#66bb6a,stroke:#2e7d32,color:#fff
    classDef sock fill:#ef9a9a,stroke:#b71c1c,color:#000

    class HostPorts host
    class Caddy proxy
    class App,AI,Scheduler,Worker,TZ app
    class PG,Redis,Garage,CH data
    class Sock sock
```

### Network Details

| Network | Type | Services | Purpose |
|---------|------|----------|---------|
| `spectra-network` | bridge (Compose) / overlay (Swarm) | All services | Service-to-service communication |
| Host port bindings | host | Caddy (:80/:443), Garage (:3900 localhost) | External access |
| Docker socket mount | bind mount | App (ro), Scheduler (ro), Worker (rw) | Container management |

### Security Boundaries

- **Caddy** is the only service with host-facing ports for user traffic
- **Garage** admin port (:3903) is bound to `127.0.0.1` only
- **PostgreSQL**, **Redis**, **ClickHouse** have no host port bindings
- **App** and **Scheduler** mount Docker socket read-only; **Worker** needs write access for sandbox containers
- All app services use `no-new-privileges` security option
- **App** container runs with `read_only: true` filesystem

---

## Related Pages

- [Architecture](architecture.md) — Agent system, execution pipeline, learning mechanisms
- [Microservices](microservices-split.md) — Service split, import boundaries, Dockerfile targets
- [Scaling](scaling.md) — Server pools, S3 storage, database scaling
- [Deployment Guide](deployment-guide.md) — Installation and production setup
- [Worker System](worker-system.md) — Job queue, sandbox execution details
