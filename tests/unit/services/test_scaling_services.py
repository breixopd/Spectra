from types import SimpleNamespace

import pytest

from spectra_scaling import docker_client, image_updater, metrics_collector, node_metrics
from spectra_scaling.healer import DiagnosticResult, ServiceHealer


@pytest.fixture(autouse=True)
def reset_image_update_state():
    image_updater._last_check.clear()
    image_updater._update_history.clear()
    yield
    image_updater._last_check.clear()
    image_updater._update_history.clear()


@pytest.mark.asyncio
async def test_image_update_dry_run_records_available_update(monkeypatch):
    async def fake_get_service(service: str):
        if service == "spectra_app":
            return SimpleNamespace(image="registry/spectra-app:stable", image_digest="old-digest")
        return None

    async def fake_get_registry_digest(image: str):
        assert image == "registry/spectra-app:stable"
        return "new-digest"

    async def fail_update_service_image(service: str, image: str):  # pragma: no cover - guard
        raise AssertionError("dry-run must not update service image")

    monkeypatch.setattr("spectra_scaling.docker_client.get_service", fake_get_service)
    monkeypatch.setattr("spectra_scaling.docker_client.get_registry_digest", fake_get_registry_digest)
    monkeypatch.setattr("spectra_scaling.docker_client.update_service_image", fail_update_service_image)

    results = await image_updater.check_and_update_services(apply=False)

    assert results == [
        image_updater.ImageUpdateResult(
            service="spectra_app",
            old_digest="old-digest",
            new_digest="new-digest",
            success=True,
            error="dry-run (auto-update disabled)",
        )
    ]
    assert image_updater.get_update_status()["spectra_app"]["update_available"] is True
    assert image_updater.get_rollback_candidates() == []


@pytest.mark.asyncio
async def test_image_update_applies_update_and_records_rollback(monkeypatch):
    async def fake_get_service(service: str):
        if service == "spectra_worker":
            return SimpleNamespace(image="registry/spectra-worker:stable", image_digest="a" * 64)
        return None

    async def fake_get_registry_digest(image: str):
        return "b" * 64

    updates: list[tuple[str, str]] = []

    async def fake_update_service_image(service: str, image: str):
        updates.append((service, image))
        return True

    async def no_sleep(seconds: int):
        assert seconds == 5

    monkeypatch.setattr("spectra_scaling.docker_client.get_service", fake_get_service)
    monkeypatch.setattr("spectra_scaling.docker_client.get_registry_digest", fake_get_registry_digest)
    monkeypatch.setattr("spectra_scaling.docker_client.update_service_image", fake_update_service_image)
    monkeypatch.setattr(image_updater.asyncio, "sleep", no_sleep)

    results = await image_updater.check_and_update_services()

    assert results[0].service == "spectra_worker"
    assert results[0].success is True
    assert updates == [("spectra_worker", "registry/spectra-worker:stable@sha256:" + "b" * 64)]
    assert image_updater.get_rollback_candidates()[0] == {
        "service": "spectra_worker",
        "previous_image": "registry/spectra-worker:stable",
        "previous_digest": "a" * 12,
        "current_digest": "b" * 12,
        "updated_at": image_updater.get_rollback_candidates()[0]["updated_at"],
    }


@pytest.mark.asyncio
async def test_image_update_reports_service_errors(monkeypatch):
    async def fake_get_service(service: str):
        if service == "spectra_caddy":
            raise RuntimeError("docker unavailable")
        return None

    monkeypatch.setattr("spectra_scaling.docker_client.get_service", fake_get_service)

    results = await image_updater.check_and_update_services()

    assert results == [
        image_updater.ImageUpdateResult(
            service="spectra_caddy",
            old_digest="",
            new_digest="",
            success=False,
            error="docker unavailable",
        )
    ]


@pytest.mark.asyncio
async def test_image_update_skips_services_without_changes(monkeypatch):
    services = {
        "spectra_ai-svc": SimpleNamespace(image="", image_digest="ignored"),
        "spectra_scheduler": SimpleNamespace(image="registry/spectra-scheduler:stable", image_digest="same"),
        "spectra_worker": SimpleNamespace(image="registry/spectra-worker:stable", image_digest="old"),
    }

    async def fake_get_service(service: str):
        return services.get(service)

    async def fake_get_registry_digest(image: str):
        return None if image.endswith("worker:stable") else "same"

    monkeypatch.setattr("spectra_scaling.docker_client.get_service", fake_get_service)
    monkeypatch.setattr("spectra_scaling.docker_client.get_registry_digest", fake_get_registry_digest)

    results = await image_updater.check_and_update_services()

    assert results == []
    status = image_updater.get_update_status()
    assert status["spectra_scheduler"]["update_available"] is False
    assert "spectra_worker" not in status


def test_collect_node_metrics_without_docker_socket(monkeypatch):
    monkeypatch.setenv("HOSTNAME", "node-a")
    monkeypatch.setattr(node_metrics.psutil, "cpu_percent", lambda interval=None: 12.5)
    monkeypatch.setattr(node_metrics.psutil, "cpu_count", lambda: 8)
    monkeypatch.setattr(node_metrics.os, "getloadavg", lambda: (1.234, 2.345, 3.456))
    monkeypatch.setattr(
        node_metrics.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=8 * 1024**3, used=3 * 1024**3, available=5 * 1024**3, percent=37.5),
    )
    monkeypatch.setattr(
        node_metrics.psutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=100 * 1024**3, used=25 * 1024**3, free=75 * 1024**3, percent=25.0),
    )
    monkeypatch.setattr(
        node_metrics.psutil,
        "net_io_counters",
        lambda: SimpleNamespace(bytes_sent=123, bytes_recv=456),
    )

    class FakeProcess:
        def cpu_percent(self, interval=None):
            return 2.2

        def memory_info(self):
            return SimpleNamespace(rss=64 * 1024 * 1024)

        def num_fds(self):
            return 9

    monkeypatch.setattr(node_metrics.psutil, "Process", FakeProcess)
    monkeypatch.setattr(node_metrics.os.path, "exists", lambda path: False)

    metrics = node_metrics.collect_node_metrics("scheduler")

    assert metrics.hostname == "node-a"
    assert metrics.service_mode == "scheduler"
    assert metrics.cpu_count == 8
    assert metrics.load_avg_1m == 1.23
    assert metrics.memory_total_mb == 8192.0
    assert len(metrics.disks) == 3
    assert metrics.container_count == 0
    assert metrics.to_dict()["process_memory_mb"] == 64.0


def test_collect_node_metrics_handles_disk_and_process_errors(monkeypatch):
    monkeypatch.setattr(node_metrics.psutil, "cpu_percent", lambda interval=None: 0.0)
    monkeypatch.setattr(node_metrics.psutil, "cpu_count", lambda: None)
    monkeypatch.setattr(node_metrics.os, "getloadavg", lambda: (0.0, 0.0, 0.0))
    monkeypatch.setattr(
        node_metrics.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=1024**3, used=512 * 1024**2, available=512 * 1024**2, percent=50.0),
    )

    def raise_disk_error(path: str):
        raise FileNotFoundError(path)

    class BrokenProcess:
        def cpu_percent(self, interval=None):
            raise node_metrics.psutil.Error("process gone")

    monkeypatch.setattr(node_metrics.psutil, "disk_usage", raise_disk_error)
    monkeypatch.setattr(node_metrics.psutil, "net_io_counters", lambda: SimpleNamespace(bytes_sent=0, bytes_recv=0))
    monkeypatch.setattr(node_metrics.psutil, "Process", BrokenProcess)
    monkeypatch.setattr(node_metrics.os.path, "exists", lambda path: False)

    metrics = node_metrics.collect_node_metrics("worker")

    assert metrics.cpu_count == 1
    assert metrics.disks == []
    assert metrics.process_cpu_percent == 0.0
    assert metrics.process_memory_mb == 0.0
    assert metrics.open_fds == 0


@pytest.mark.asyncio
async def test_collect_node_metrics_counts_docker_containers_outside_event_loop(monkeypatch):
    monkeypatch.setattr(node_metrics.os.path, "exists", lambda path: path == "/var/run/docker.sock")

    async def fake_count_running_containers():
        return 7

    monkeypatch.setattr("spectra_scaling.docker_client.count_running_containers", fake_count_running_containers)

    # The collector should use the synchronous Docker SDK path when an event loop is already running.
    fake_client = SimpleNamespace(
        containers=SimpleNamespace(list=lambda: [object(), object()]),
        close=lambda: None,
    )
    monkeypatch.setattr("docker.from_env", lambda timeout=5: fake_client)

    metrics = node_metrics.collect_node_metrics("api")

    assert metrics.container_count == 2


@pytest.mark.asyncio
async def test_service_healer_resolves_by_restart(monkeypatch):
    backend = SimpleNamespace(restart=lambda service: None)

    async def restart(service: str):
        return SimpleNamespace(success=True)

    backend.restart = restart
    notifier = SimpleNamespace(notify=lambda *args, **kwargs: None)
    healer = ServiceHealer(backend, notifier)

    async def collect_logs(service: str):
        return "recent logs"

    monkeypatch.setattr(healer, "_collect_service_logs", collect_logs)

    async def healthy_deps():
        return [{"name": "postgresql", "result": "healthy", "detail": "ok"}]

    async def ok_resources():
        return [{"name": "memory", "result": "ok", "detail": "20% used"}]

    monkeypatch.setattr(healer, "_check_dependencies", healthy_deps)
    monkeypatch.setattr(healer, "_check_resources", ok_resources)

    result = await healer.diagnose_and_heal("spectra_app")

    assert result.resolved is True
    assert result.summary == "Resolved by force-restart"
    assert healer.get_heal_history()[0]["service"] == "spectra_app"
    assert healer._consecutive_failures["spectra_app"] == 0


@pytest.mark.asyncio
async def test_service_healer_notifies_after_failed_recovery(monkeypatch):
    async def restart(service: str):
        return SimpleNamespace(success=False)

    notifications: list[tuple[str, str, str]] = []

    async def notify(title: str, body: str, level: str):
        notifications.append((title, body, level))

    healer = ServiceHealer(SimpleNamespace(restart=restart), SimpleNamespace(notify=notify))

    async def collect_logs(service: str):
        return ""

    monkeypatch.setattr(healer, "_collect_service_logs", collect_logs)

    async def unhealthy_deps():
        return [{"name": "redis", "result": "unhealthy", "detail": "timeout"}]

    async def critical_resources():
        return [{"name": "disk", "result": "critical", "detail": "1.0GB free"}]

    monkeypatch.setattr(healer, "_check_dependencies", unhealthy_deps)
    monkeypatch.setattr(healer, "_check_resources", critical_resources)

    result = await healer.diagnose_and_heal("spectra_worker", "crash-loop")

    assert result.resolved is False
    assert "Consecutive failures: 1" in result.summary
    assert notifications[0][0] == "Service Recovery Failed: spectra_worker"
    assert "redis: unhealthy" in notifications[0][1]
    assert notifications[0][2] == "critical"


@pytest.mark.asyncio
async def test_service_healer_resource_checks_report_warning_and_critical(monkeypatch):
    healer = ServiceHealer(SimpleNamespace(), SimpleNamespace())
    states = [
        (
            SimpleNamespace(percent=90.0),
            SimpleNamespace(free=8 * 1024**3),
        ),
        (
            SimpleNamespace(percent=96.0),
            SimpleNamespace(free=4 * 1024**3),
        ),
    ]

    def fake_virtual_memory():
        return states[0][0]

    def fake_disk_usage(path: str):
        assert path == "/"
        return states.pop(0)[1]

    monkeypatch.setattr("psutil.virtual_memory", fake_virtual_memory)
    monkeypatch.setattr("psutil.disk_usage", fake_disk_usage)

    warning = await healer._check_resources()
    critical = await healer._check_resources()

    assert warning == [
        {"name": "memory", "result": "warning", "detail": "90.0% used"},
        {"name": "disk", "result": "warning", "detail": "8.0GB free"},
    ]
    assert critical == [
        {"name": "memory", "result": "critical", "detail": "96.0% used"},
        {"name": "disk", "result": "critical", "detail": "4.0GB free"},
    ]


def test_diagnostic_summary_formats_checks_and_attempts():
    result = DiagnosticResult(
        timestamp="2026-04-28T00:00:00+00:00",
        service="spectra_ai-svc",
        issue="unhealthy",
        checks_performed=[{"name": "logs", "result": "collected", "detail": "ok"}],
        recovery_attempted=[{"action": "restart", "success": False, "detail": "denied"}],
    )

    summary = ServiceHealer._build_diagnostic_summary(result)

    assert "Service: spectra_ai-svc" in summary
    assert "logs: collected" in summary
    assert "restart: FAILED" in summary


def test_compose_service_metrics_groups_replicas_by_label():
    collector = metrics_collector.MetricsCollector()
    containers = [
        docker_client.ContainerStats(
            container_id="a",
            name="docker-worker-1",
            cpu_percent=0.0,
            memory_mb=0.0,
            memory_limit_mb=0.0,
            labels={"com.docker.compose.service": "worker"},
        ),
        docker_client.ContainerStats(
            container_id="b",
            name="docker-worker-2",
            cpu_percent=0.0,
            memory_mb=0.0,
            memory_limit_mb=0.0,
            labels={"com.docker.compose.service": "worker"},
        ),
        docker_client.ContainerStats(
            container_id="c",
            name="spectra-app",
            cpu_percent=0.0,
            memory_mb=0.0,
            memory_limit_mb=0.0,
            labels={"com.docker.compose.service": "app"},
        ),
    ]

    services = collector._compose_service_metrics(containers)

    assert services["spectra_worker"].replicas == 2
    assert services["spectra_worker"].desired_replicas == 2
    assert services["spectra_worker"].running_tasks == 2
    assert services["spectra_app"].replicas == 1


@pytest.mark.asyncio
async def test_metrics_collector_returns_compose_replicas_when_swarm_unavailable(monkeypatch):
    async def no_swarm_services():
        return []

    async def compose_containers():
        return [
            docker_client.ContainerStats(
                container_id="a",
                name="docker-worker-1",
                cpu_percent=0.0,
                memory_mb=0.0,
                memory_limit_mb=0.0,
                labels={"com.docker.compose.service": "worker"},
            ),
            docker_client.ContainerStats(
                container_id="b",
                name="docker-worker-2",
                cpu_percent=0.0,
                memory_mb=0.0,
                memory_limit_mb=0.0,
                labels={"com.docker.compose.service": "worker"},
            ),
        ]

    async def slow_stats():
        return []

    async def timeout_wait_for(coro, timeout):
        coro.close()
        raise TimeoutError

    monkeypatch.setattr("spectra_scaling.metrics_collector.list_services", no_swarm_services, raising=False)
    monkeypatch.setattr("spectra_scaling.docker_client.list_services", no_swarm_services)
    monkeypatch.setattr("spectra_scaling.docker_client.list_running_containers", compose_containers)
    monkeypatch.setattr("spectra_scaling.docker_client.get_container_stats", slow_stats)
    monkeypatch.setattr(metrics_collector.asyncio, "wait_for", timeout_wait_for)

    services = await metrics_collector.MetricsCollector()._collect_service_metrics()

    assert services["spectra_worker"].replicas == 2


@pytest.mark.asyncio
async def test_metrics_collector_marks_partial_service_stats_invalid(monkeypatch):
    async def swarm_services():
        return [
            SimpleNamespace(
                name="spectra_worker",
                running_tasks=2,
                desired_replicas=2,
                failed_tasks=0,
            )
        ]

    async def partial_stats():
        return [
            docker_client.ContainerStats(
                container_id="a",
                name="spectra_worker.1.node",
                cpu_percent=15.0,
                memory_mb=32.0,
                memory_limit_mb=128.0,
                labels={},
            )
        ]

    monkeypatch.setattr("spectra_scaling.docker_client.list_services", swarm_services)
    monkeypatch.setattr("spectra_scaling.docker_client.get_container_stats", partial_stats)

    services = await metrics_collector.MetricsCollector()._collect_service_metrics()

    assert services["spectra_worker"].valid is False


@pytest.mark.asyncio
async def test_metrics_collector_rejects_non_finite_queue_age(monkeypatch):
    async def broken_queue_metrics():
        return {
            "depth": 1,
            "in_progress": 0,
            "avg_wait_seconds": 0.5,
            "oldest_job_age_seconds": float("nan"),
        }

    monkeypatch.setattr("spectra_infra.queue.queue_metrics", broken_queue_metrics)

    queue = await metrics_collector.MetricsCollector()._collect_queue_metrics()

    assert queue.valid is False
    assert queue.oldest_job_secs == 0.0


def test_docker_client_detects_non_manager_swarm_socket():
    client = SimpleNamespace(info=lambda: {"Swarm": {"ControlAvailable": False}})

    assert docker_client._is_swarm_manager(client) is False


def test_docker_client_detects_manager_swarm_socket():
    client = SimpleNamespace(info=lambda: {"Swarm": {"ControlAvailable": True}})

    assert docker_client._is_swarm_manager(client) is True


def test_parse_service_failed_tasks_from_task_state_not_desired_minus_running():
    """Replica gap during rollout must not be counted as failed_tasks (healer false positives)."""
    attrs = {
        "Spec": {
            "Mode": {"Replicated": {"Replicas": 3}},
            "TaskTemplate": {"ContainerSpec": {"Image": "spectra/app:latest"}},
        }
    }

    def tasks(filters=None):
        if filters == {"desired-state": "running"}:
            return [
                {"Status": {"State": "running"}, "NodeID": "n1", "Version": {"Index": 5}},
                {"Status": {"State": "starting"}, "NodeID": "", "Version": {"Index": 4}},
            ]
        return [
            {"Status": {"State": "running"}, "NodeID": "n1", "Version": {"Index": 5}},
            {"Status": {"State": "starting"}, "NodeID": "", "Version": {"Index": 4}},
        ]

    svc = SimpleNamespace(name="spectra_app", attrs=attrs, tasks=tasks)
    info = docker_client._parse_service(svc)
    assert info.running_tasks == 1
    assert info.desired_replicas == 3
    assert info.failed_tasks == 0


def test_parse_service_counts_actively_failed_task():
    """A failed task Swarm still wants running is an active failure."""
    attrs = {
        "Spec": {
            "Mode": {"Replicated": {"Replicas": 2}},
            "TaskTemplate": {"ContainerSpec": {"Image": "spectra/app:latest"}},
        }
    }

    def tasks(filters=None):
        if filters == {"desired-state": "running"}:
            return [
                {"Status": {"State": "running"}, "NodeID": "n1", "Version": {"Index": 3}},
            ]
        return [
            {"ID": "t1", "Status": {"State": "running"}, "NodeID": "n1", "Version": {"Index": 3}},
            {"ID": "t2", "DesiredState": "running", "Status": {"State": "failed"}, "Version": {"Index": 2}},
        ]

    svc = SimpleNamespace(name="spectra_app", attrs=attrs, tasks=tasks)
    info = docker_client._parse_service(svc)
    assert info.failed_tasks == 1


def test_parse_service_counts_recent_failure_within_window():
    """A superseded failure inside the active-failure window still counts (crash-loop)."""
    from datetime import UTC, datetime

    recent = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f000Z")
    attrs = {
        "Spec": {
            "Mode": {"Replicated": {"Replicas": 1}},
            "TaskTemplate": {"ContainerSpec": {"Image": "spectra/w:latest"}},
        }
    }

    def tasks(filters=None):
        if filters == {"desired-state": "running"}:
            return [{"Status": {"State": "running"}, "NodeID": "n1", "Version": {"Index": 10}}]
        return [
            {"ID": "t1", "Status": {"State": "running"}, "NodeID": "n1", "Version": {"Index": 10}},
            {
                "ID": "t2",
                "DesiredState": "shutdown",
                "Status": {"State": "failed", "Timestamp": recent},
                "Version": {"Index": 9},
            },
            {"ID": "t3", "DesiredState": "shutdown", "Status": {"State": "shutdown"}, "Version": {"Index": 8}},
        ]

    svc = SimpleNamespace(name="spectra_worker", attrs=attrs, tasks=tasks)
    info = docker_client._parse_service(svc)
    assert info.failed_tasks == 1


def test_parse_service_ignores_old_superseded_failures():
    """Old failures outside the window must NOT count (no perpetual self-heal)."""
    attrs = {
        "Spec": {
            "Mode": {"Replicated": {"Replicas": 1}},
            "TaskTemplate": {"ContainerSpec": {"Image": "spectra/w:latest"}},
        }
    }

    def tasks(filters=None):
        if filters == {"desired-state": "running"}:
            return [{"Status": {"State": "running"}, "NodeID": "n1", "Version": {"Index": 10}}]
        return [
            {"ID": "t1", "Status": {"State": "running"}, "NodeID": "n1", "Version": {"Index": 10}},
            {
                "ID": "t2",
                "DesiredState": "shutdown",
                "Status": {"State": "failed", "Timestamp": "2020-01-01T00:00:00.000000000Z"},
                "Version": {"Index": 9},
            },
        ]

    svc = SimpleNamespace(name="spectra_worker", attrs=attrs, tasks=tasks)
    info = docker_client._parse_service(svc)
    assert info.failed_tasks == 0


def test_parse_mem_units():
    assert metrics_collector._parse_mem("1GiB") == 1024
    assert metrics_collector._parse_mem("512MiB") == 512
    assert metrics_collector._parse_mem("1024KiB") == 1
    assert metrics_collector._parse_mem("bad") == 0.0


@pytest.mark.asyncio
async def test_collect_system_metrics(monkeypatch):
    monkeypatch.setattr(metrics_collector.psutil, "cpu_percent", lambda interval=1: 12.5)
    monkeypatch.setattr(
        metrics_collector.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(percent=40.0, available=2 * 1024 * 1024),
    )
    monkeypatch.setattr(
        metrics_collector.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=10 * 1024**3, used=4 * 1024**3, free=6 * 1024**3),
    )
    monkeypatch.setattr(metrics_collector.psutil, "getloadavg", lambda: (1.0, 2.0, 3.0))

    system = await metrics_collector.MetricsCollector()._collect_system_metrics()

    assert system.cpu_percent == 12.5
    assert system.memory_percent == 40.0
    assert system.memory_available_mb == 2.0
    assert round(system.disk_percent, 1) == 40.0
    assert round(system.disk_free_gb, 1) == 6.0
    assert system.load_avg_1m == 1.0


@pytest.mark.asyncio
async def test_collect_queue_metrics(monkeypatch):
    async def fake_queue_metrics():
        return {
            "depth": 3,
            "in_progress": 2,
            "completed": 10,
            "avg_wait_seconds": 1.5,
            "oldest_job_age_seconds": 9.0,
        }

    monkeypatch.setattr("spectra_infra.queue.queue_metrics", fake_queue_metrics)

    queue = await metrics_collector.MetricsCollector()._collect_queue_metrics()

    assert queue.depth == 3
    assert queue.in_progress == 2
    assert queue.completed == 10
    assert queue.avg_wait_secs == 1.5
    assert queue.oldest_job_secs == 9.0
