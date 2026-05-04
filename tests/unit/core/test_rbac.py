"""Tests for spectra_api.authz module."""

from spectra_api.authz import ROLE_PERMISSIONS, Permission, has_permission


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
            "view_monitoring",
        }
        actual = {p.value for p in Permission}
        assert expected == actual


class TestRolePermissions:
    def test_admin_has_all_permissions(self):
        admin_perms = ROLE_PERMISSIONS["admin"]
        for p in Permission:
            assert p in admin_perms

    def test_staff_has_only_view_and_support_permissions(self):
        staff_perms = ROLE_PERMISSIONS["staff"]
        assert Permission.VIEW_MISSIONS in staff_perms
        assert Permission.VIEW_FINDINGS in staff_perms
        assert Permission.VIEW_TARGETS in staff_perms
        assert Permission.VIEW_REPORTS in staff_perms
        assert Permission.MANAGE_USERS in staff_perms
        assert Permission.VIEW_AUDIT_LOG in staff_perms
        assert Permission.VIEW_MONITORING in staff_perms
        # Should NOT have write/manage permissions
        assert Permission.CREATE_MISSIONS not in staff_perms
        assert Permission.MANAGE_SETTINGS not in staff_perms
        assert Permission.SHELL_ACCESS not in staff_perms

    def test_user_has_operational_permissions(self):
        user_perms = ROLE_PERMISSIONS["user"]
        assert Permission.CREATE_MISSIONS in user_perms
        assert Permission.USE_TOOLS in user_perms
        assert Permission.SHELL_ACCESS in user_perms
        # Should NOT have admin-only permissions
        assert Permission.MANAGE_SETTINGS not in user_perms
        assert Permission.MANAGE_USERS not in user_perms
        # Users should NOT view audit log
        assert Permission.VIEW_AUDIT_LOG not in user_perms

    def test_three_roles_defined(self):
        assert set(ROLE_PERMISSIONS.keys()) == {"admin", "staff", "user"}


class TestHasPermission:
    def test_admin_can_manage_settings(self):
        assert has_permission("admin", Permission.MANAGE_SETTINGS) is True

    def test_admin_can_manage_users(self):
        assert has_permission("admin", Permission.MANAGE_USERS) is True

    def test_staff_can_view_missions(self):
        assert has_permission("staff", Permission.VIEW_MISSIONS) is True

    def test_staff_cannot_create_missions(self):
        assert has_permission("staff", Permission.CREATE_MISSIONS) is False

    def test_user_can_use_tools(self):
        assert has_permission("user", Permission.USE_TOOLS) is True

    def test_user_cannot_manage_users(self):
        assert has_permission("user", Permission.MANAGE_USERS) is False

    def test_unknown_role_has_no_permissions(self):
        assert has_permission("hacker", Permission.VIEW_MISSIONS) is False

    def test_empty_role_has_no_permissions(self):
        assert has_permission("", Permission.VIEW_MISSIONS) is False
