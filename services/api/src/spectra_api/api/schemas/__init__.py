"""Pydantic schemas for API requests and responses.

Schemas live in domain modules: ``auth``, ``common``, ``cve``, ``finding``,
``mission``, ``system``, ``tool``. Import from those submodules (for example
``from spectra_api.api.schemas.auth import Token``), not from this package.
"""
