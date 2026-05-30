"""
PostgreSQL Job Queue Worker for Spectra Tools Container.

This worker runs ONLY inside the tools container and handles:
- Tool execution (runs commands directly, no docker exec)
- Golden image rebuild/verification after plugin changes
- Tool status syncing to cache
- Background plugin reload when new plugins are uploaded

Split into submodules:
- tool_jobs: Tool execution, installation, status sync
- command_jobs: Arbitrary command and script execution
- vpn_jobs: VPN connection management
- helpers: Internal utilities (command runner, stats tracking)
- lifecycle: Startup, shutdown, heartbeat
"""

from __future__ import annotations

from spectra_system.maintenance import run_all_cleanup
from spectra_worker.command_jobs import execute_script_job, run_command_job
from spectra_worker.lifecycle import heartbeat_loop, shutdown, startup
from spectra_worker.notification_jobs import (
    send_critical_finding_alert,
    send_mission_completion_notification,
    send_webhook_notification,
)
from spectra_worker.report_jobs import generate_executive_summary, generate_mission_report
from spectra_worker.tool_jobs import (
    build_golden_image_job,
    execute_tool_job,
    get_tool_status_job,
    install_all_tools_job,
    install_tool_job,
    reload_plugins_job,
    sync_all_status_job,
    uninstall_tool_job,
)
from spectra_worker.training_jobs import run_fine_tuning_job
from spectra_worker.vpn_jobs import (
    vpn_connect_job,
    vpn_disconnect_job,
    vpn_status_job,
    vpn_test_job,
)

_WORKER_FUNCTIONS = [
    execute_tool_job,
    build_golden_image_job,
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
    # Training
    run_fine_tuning_job,
]

__all__ = [
    "_WORKER_FUNCTIONS",
    "build_golden_image_job",
    "execute_script_job",
    "execute_tool_job",
    "generate_executive_summary",
    "generate_mission_report",
    "get_tool_status_job",
    "heartbeat_loop",
    "install_all_tools_job",
    "install_tool_job",
    "reload_plugins_job",
    "run_all_cleanup",
    "run_command_job",
    "run_fine_tuning_job",
    "send_critical_finding_alert",
    "send_mission_completion_notification",
    "send_webhook_notification",
    "shutdown",
    "startup",
    "sync_all_status_job",
    "uninstall_tool_job",
    "vpn_connect_job",
    "vpn_disconnect_job",
    "vpn_status_job",
    "vpn_test_job",
]
