"""Tests for the email service: providers, templates, and EmailService."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email.providers.console import ConsoleProvider
from app.services.email.service import EmailService
from app.services.email.templates import TEMPLATES

# ---------------------------------------------------------------------------
# ConsoleProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_console_provider_send_logs_output(caplog):
    """ConsoleProvider.send() should log the email and return True."""
    provider = ConsoleProvider()
    with caplog.at_level(logging.INFO, logger="spectra.email.console"):
        result = await provider.send(
            to="user@example.com",
            subject="Test Subject",
            html_body="<p>Hello</p>",
        )
    assert result is True
    assert "user@example.com" in caplog.text
    assert "Test Subject" in caplog.text


@pytest.mark.asyncio
async def test_console_provider_send_prefers_text_body(caplog):
    """When text_body is provided, ConsoleProvider logs it instead of html."""
    provider = ConsoleProvider()
    with caplog.at_level(logging.INFO, logger="spectra.email.console"):
        await provider.send(
            to="a@b.com",
            subject="S",
            html_body="<p>HTML</p>",
            text_body="Plain text body",
        )
    assert "Plain text body" in caplog.text


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------


def test_templates_dict_contains_expected_keys():
    expected = {"welcome", "password_reset", "mission_complete", "alert", "subscription", "email_verification"}
    assert expected.issubset(set(TEMPLATES.keys()))


def test_welcome_template_renders():
    html = TEMPLATES["welcome"].format(username="Alice", login_url="https://app.example.com")
    assert "Alice" in html
    assert "https://app.example.com" in html


def test_password_reset_template_renders():
    html = TEMPLATES["password_reset"].format(username="Bob", reset_url="https://reset.link")
    assert "Bob" in html
    assert "https://reset.link" in html


def test_mission_complete_template_renders():
    html = TEMPLATES["mission_complete"].format(
        username="Eve",
        target="10.0.0.1",
        status="completed",
        finding_count="5",
        report_url="https://report",
    )
    assert "10.0.0.1" in html
    assert "5" in html


def test_alert_template_renders():
    html = TEMPLATES["alert"].format(
        username="Mallory",
        alert_title="Critical",
        alert_message="Something happened",
    )
    assert "Critical" in html
    assert "Something happened" in html


# ---------------------------------------------------------------------------
# EmailService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_service_send_email_delegates_to_provider():
    mock_provider = AsyncMock()
    mock_provider.send.return_value = True

    svc = EmailService(provider=mock_provider)
    result = await svc.send_email("x@y.com", "subj", "<p>body</p>")

    assert result is True
    mock_provider.send.assert_awaited_once_with("x@y.com", "subj", "<p>body</p>", None)


@pytest.mark.asyncio
async def test_email_service_send_template_renders_and_sends():
    mock_provider = AsyncMock()
    mock_provider.send.return_value = True

    svc = EmailService(provider=mock_provider)
    result = await svc.send_template(
        to="user@test.com",
        template_name="welcome",
        subject="Welcome!",
        username="Tester",
        login_url="https://login",
    )

    assert result is True
    call_args = mock_provider.send.call_args
    html_sent = call_args[0][2]
    assert "Tester" in html_sent
    assert "https://login" in html_sent


@pytest.mark.asyncio
async def test_email_service_send_template_unknown_returns_false():
    mock_provider = AsyncMock()
    svc = EmailService(provider=mock_provider)
    result = await svc.send_template(
        to="user@test.com",
        template_name="nonexistent_template",
        subject="Nope",
    )
    assert result is False
    mock_provider.send.assert_not_awaited()


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


@patch("app.services.email.service.settings")
def test_get_provider_returns_smtp_when_host_configured(mock_settings):
    """When SMTP_HOST is set, _get_provider returns SMTPProvider."""
    mock_settings.SMTP_HOST = "smtp.example.com"
    from app.services.email.providers.smtp import SMTPProvider
    from app.services.email.service import _get_provider

    provider = _get_provider()
    assert isinstance(provider, SMTPProvider)


@patch("app.services.email.service.settings")
def test_get_provider_returns_console_when_no_smtp(mock_settings):
    """When SMTP_HOST is empty, _get_provider returns ConsoleProvider."""
    mock_settings.SMTP_HOST = ""
    from app.services.email.service import _get_provider

    provider = _get_provider()
    assert isinstance(provider, ConsoleProvider)


# ---------------------------------------------------------------------------
# SMTP provider (mocked aiosmtplib)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.services.email.providers.smtp.settings")
async def test_smtp_provider_send_success(mock_settings):
    mock_settings.SMTP_HOST = "smtp.test.com"
    mock_settings.SMTP_PORT = 587
    mock_settings.SMTP_USER = "user"
    mock_settings.SMTP_PASSWORD = MagicMock()
    mock_settings.SMTP_PASSWORD.get_secret_value.return_value = "pass"
    mock_settings.SMTP_USE_TLS = True
    mock_settings.SMTP_FROM = "noreply@test.com"

    from app.services.email.providers.smtp import SMTPProvider

    provider = SMTPProvider()

    with patch("app.services.email.providers.smtp.aiosmtplib", create=True) as mock_aio:
        mock_send = AsyncMock()
        mock_aio.send = mock_send

        # Patch the import inside the method
        import sys

        sys.modules["aiosmtplib"] = mock_aio

        result = await provider.send("to@test.com", "Subj", "<p>Hi</p>")
        assert result is True
        mock_send.assert_awaited_once()

        # Clean up
        del sys.modules["aiosmtplib"]
