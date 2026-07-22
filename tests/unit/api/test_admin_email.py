"""Security tests for administrator email rendering."""

from spectra_api.api.routers.admin.email import _render_announcement_content


def test_announcement_content_is_html_escaped_by_default():
    rendered = _render_announcement_content("<img src=x onerror=alert(1)>", "hello <script>alert(1)</script>")

    assert "<img" not in rendered
    assert "<script>" not in rendered
    assert "&lt;img" in rendered
    assert "&lt;script&gt;" in rendered
