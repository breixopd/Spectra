"""Authentication Router — re-exports combined router from sub-modules."""

from fastapi import APIRouter

router = APIRouter()

from app.api.routers.auth.login import router as login_router
from app.api.routers.auth.password import router as password_router
from app.api.routers.auth.registration import router as registration_router
from app.api.routers.auth.session import router as session_router
from app.api.routers.auth.totp import router as totp_router

router.include_router(login_router)
router.include_router(registration_router)
router.include_router(password_router)
router.include_router(totp_router)
router.include_router(session_router)

# Re-export public symbols for backward compatibility with tests and external consumers
from app.api.routers.auth._helpers import (  # noqa: E402, F401
    ACCESS_COOKIE_KEY,
    ACCESS_COOKIE_PATH,
    AUTH_COOKIE_SAMESITE,
    LOCKOUT_THRESHOLD_1,
    LOCKOUT_THRESHOLD_2,
    REFRESH_COOKIE_KEY,
    REFRESH_COOKIE_PATH,
    REFRESH_TOKEN_MAX_AGE,
    _check_lockout,
    _clear_auth_cookies,
    _consume_totp_code,
    _record_failure,
    _record_success,
    _set_auth_cookies,
    _should_use_secure_auth_cookies,
    _used_totp_codes,
)
from app.api.routers.auth.login import login_for_access_token, logout, refresh_token  # noqa: E402, F401
from app.api.routers.auth.password import change_password  # noqa: E402, F401
from app.api.routers.auth.registration import (  # noqa: E402, F401
    check_setup_status,
    setup_admin_user,
)
from app.api.routers.auth.session import (  # noqa: E402, F401
    delete_account,
    export_user_data,
    get_current_profile,
    update_profile,
)
from app.api.routers.auth.session import (
    toggle_restrict_processing as restrict_processing,
)
from app.api.routers.auth.totp import (  # noqa: E402, F401
    cancel_mfa,
    mfa_disable,
    mfa_setup,
    mfa_verify_login,
    mfa_verify_setup,
)
from app.services.system.audit import log_event as audit_log_event  # noqa: E402, F401
