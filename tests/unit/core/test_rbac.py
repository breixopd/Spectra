"""Tests for app.core.rbac module."""

from app.core.rbac import ROLE_PERMISSIONS, Permission, has_permission


class TestPermissionEnum:
    def test_all_permissions_are_strings(self):
        for p in Permission:
            assert isinstance(p.value, str)

    def test_expected_permissions_exist(self):
        expected = {
            "view_missions",
            "create_missions",
            "manage_missions",
            "view_findings",
            "manage_findings",
            "view_targets",
            "manage_targets",
            "use_tools",
            "manage_tools",
            "view_reports",
            "manage_settings",
            "manage_users",
            "view_audit_log",
            "shell_access",
            "rollback_own_actions",
        }
        actual = {p.value for p in Permission}
        assert expected == actual


class TestRolePermissions:
    def test_admin_has_all_permissions(self):
        admin_perms = ROLE_PERMISSIONS["admin"]
        for p in Permission:
            assert p in admin_perms

    def test_viewer_has_only_view_permissions(self):
        viewer_perms = ROLE_PERMISSIONS["viewer"]
        assert Permission.VIEW_MISSIONS in viewer_perms
        assert Permission.VIEW_FINDINGS in viewer_perms
        assert Permission.VIEW_TARGETS in viewer_perms
        assert Permission.VIEW_REPORTS in viewer_perms
        # Should NOT have write/manage permissions
        assert Permission.CREATE_MISSIONS not in viewer_perms
        assert Permission.MANAGE_SETTINGS not in viewer_perms
        assert Permission.MANAGE_USERS not in viewer_perms
        assert Permission.SHELL_ACCESS not in viewer_perms

    def test_operator_has_operational_permissions(self):
        op_perms = ROLE_PERMISSIONS["operator"]
        assert Permission.CREATE_MISSIONS in op_perms
        assert Permission.USE_TOOLS in op_perms
        assert Permission.SHELL_ACCESS in op_perms
        # Should NOT have admin-only permissions
        assert Permission.MANAGE_SETTINGS not in op_perms
        assert Permission.MANAGE_USERS not in op_perms
        # Operators CAN view their own audit log
        assert Permission.VIEW_AUDIT_LOG in op_perms

    def test_three_roles_defined(self):
        assert set(ROLE_PERMISSIONS.keys()) == {"admin", "operator", "viewer"}


class TestHasPermission:
    def test_admin_can_manage_settings(self):
        assert has_permission("admin", Permission.MANAGE_SETTINGS) is True

    def test_admin_can_manage_users(self):
        assert has_permission("admin", Permission.MANAGE_USERS) is True

    def test_viewer_can_view_missions(self):
        assert has_permission("viewer", Permission.VIEW_MISSIONS) is True

    def test_viewer_cannot_create_missions(self):
        assert has_permission("viewer", Permission.CREATE_MISSIONS) is False

    def test_operator_can_use_tools(self):
        assert has_permission("operator", Permission.USE_TOOLS) is True

    def test_operator_cannot_manage_users(self):
        assert has_permission("operator", Permission.MANAGE_USERS) is False

    def test_unknown_role_has_no_permissions(self):
        assert has_permission("hacker", Permission.VIEW_MISSIONS) is False

    def test_empty_role_has_no_permissions(self):
        assert has_permission("", Permission.VIEW_MISSIONS) is False
