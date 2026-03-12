"""
PostgreSQL Job Queue Worker for Spectra Tools Container.

This worker runs ONLY inside the tools container and handles:
- Tool execution (runs commands directly, no docker exec)
- Tool installation/uninstallation
- Tool status syncing to cache
- Background plugin installation when new plugins are uploaded

Split into submodules:
- tool_jobs: Tool execution, installation, status sync
- command_jobs: Arbitrary command and script execution
- vpn_jobs: VPN connection management
- helpers: Internal utilities (command runner, stats tracking)
- lifecycle: Startup, shutdown, heartbeat
"""

from __future__ import annotations

import logging

from app.worker.cleanup_jobs import run_all_cleanup
from app.worker.command_jobs import execute_script_job, run_command_job
from app.worker.lifecycle import heartbeat_loop, shutdown, startup
from app.worker.notification_jobs import (
    send_critical_finding_alert,
    send_mission_completion_notification,
    send_webhook_notification,
)
from app.worker.report_jobs import generate_executive_summary, generate_mission_report
from app.worker.tool_jobs import (
    execute_tool_job,
    get_tool_status_job,
    install_all_tools_job,
    install_tool_job,
    reload_plugins_job,
    sync_all_status_job,
    uninstall_tool_job,
)
from app.worker.vpn_jobs import (
    vpn_connect_job,
    vpn_disconnect_job,
    vpn_status_job,
    vpn_test_job,
)

logger = logging.getLogger("spectra.worker")

logger.info(
    "Worker module loaded: %d job functions registered",
    len([
        execute_tool_job, install_tool_job, uninstall_tool_job,
        install_all_tools_job, reload_plugins_job, get_tool_status_job,
        sync_all_status_job, run_command_job, execute_script_job,
        vpn_connect_job, vpn_disconnect_job, vpn_status_job, vpn_test_job,
        run_all_cleanup, send_webhook_notification,
        send_mission_completion_notification, send_critical_finding_alert,
        generate_mission_report, generate_executive_summary,
    ]),
)

_WORKER_FUNCTIONS = [
    execute_tool_job,
    install_tool_job,
    uninstall_tool_job,
    install_all_tools_job,
    reload_plugins_job,
    get_tool_status_job,
    sync_all_status_job,
    run_command_job,
    execute_script_job,
    vpn_connect_job,
    vpn_disconnect_job,
    vpn_status_job,
    vpn_test_job,
    # Cleanup
    run_all_cleanup,
    # Notifications
    send_webhook_notification,
    send_mission_completion_notification,
    send_critical_finding_alert,
    # Reports
    generate_mission_report,
    generate_executive_summary,
]

__all__ = [
    # Tool jobs
    "execute_tool_job",
    "install_tool_job",
    "uninstall_tool_job",
    "install_all_tools_job",
    "reload_plugins_job",
    "get_tool_status_job",
    "sync_all_status_job",
    # Command jobs
    "run_command_job",
    "execute_script_job",
    # VPN jobs
    "vpn_connect_job",
    "vpn_disconnect_job",
    "vpn_status_job",
    "vpn_test_job",
    # Cleanup jobs
    "run_all_cleanup",
    # Notification jobs
    "send_webhook_notification",
    "send_mission_completion_notification",
    "send_critical_finding_alert",
    # Report jobs
    "generate_mission_report",
    "generate_executive_summary",
    # Lifecycle
    "startup",
    "shutdown",
    "heartbeat_loop",
    # Registry
    "_WORKER_FUNCTIONS",
]
