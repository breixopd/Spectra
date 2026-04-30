"""Authentication router — combined APIRouter from auth sub-modules."""

from fastapi import APIRouter

router = APIRouter()

from spectra_api.api.routers.auth.login import router as login_router
from spectra_api.api.routers.auth.password import router as password_router
from spectra_api.api.routers.auth.registration import router as registration_router
from spectra_api.api.routers.auth.session import router as session_router
from spectra_api.api.routers.auth.totp import router as totp_router

router.include_router(login_router)
router.include_router(registration_router, include_in_schema=False)
router.include_router(password_router)
router.include_router(totp_router)
router.include_router(session_router)
