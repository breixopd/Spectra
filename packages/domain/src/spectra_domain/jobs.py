"""Shared job queue contract names."""

from __future__ import annotations

from enum import StrEnum


class WorkerJobName(StrEnum):
    EXECUTE_TOOL = "execute_tool_job"
    INSTALL_TOOL = "install_tool_job"
    UNINSTALL_TOOL = "uninstall_tool_job"
    BUILD_GOLDEN_IMAGE = "build_golden_image_job"
    INSTALL_ALL_TOOLS = "install_all_tools_job"
    RELOAD_PLUGINS = "reload_plugins_job"
    GET_TOOL_STATUS = "get_tool_status_job"
    SYNC_ALL_STATUS = "sync_all_status_job"
    RUN_COMMAND = "run_command_job"
    EXECUTE_SCRIPT = "execute_script_job"
    VPN_CONNECT = "vpn_connect_job"
    VPN_DISCONNECT = "vpn_disconnect_job"
    VPN_STATUS = "vpn_status_job"
    VPN_TEST = "vpn_test_job"
