from unittest.mock import MagicMock

import pytest

from spectra_tools.adapter import CommandToolAdapter
from spectra_tools_core.models import ToolConfig


class TestToolAdapterParsing:
    @pytest.fixture
    def adapter(self):
        config = MagicMock(spec=ToolConfig)
        # Setup nested parsing config
        config.parsing = MagicMock()
        config.parsing.row_tag = "item"
        adapter = CommandToolAdapter(config)
        return adapter

    def test_parse_nmap_xml(self, adapter):
        xml_content = """<?xml version="1.0"?>
        <nmaprun>
            <host>
                <address addr="192.168.1.1" addrtype="ipv4"/>
                <ports>
                    <port protocol="tcp" portid="80">
                        <state state="open" reason="syn-ack"/>
                        <service name="http" product="Apache" version="2.4.41"/>
                    </port>
                    <port protocol="tcp" portid="22">
                        <state state="closed"/>
                    </port>
                </ports>
            </host>
        </nmaprun>"""

        # Use _parse_xml which delegates to parsers now
        findings = adapter.parser._parse_xml(xml_content)

        # _parse_xml returns list of dicts. Since it's nmaprun, it returns list of findings.
        assert len(findings) == 1
        assert findings[0]["portid"] == "80"
        assert findings[0]["service"] == "http"
        assert findings[0]["product"] == "Apache"
        assert findings[0]["ip"] == "192.168.1.1"

    def test_parse_simple_xml(self, adapter):
        xml_content = """<root>
            <item>
                <id>1</id>
                <severity>high</severity>
            </item>
            <item>
                <id>2</id>
                <severity>low</severity>
            </item>
        </root>"""

        adapter.config.parsing.row_tag = "item"
        findings = adapter.parser._parse_xml(xml_content)

        # Parser finds "item" container elements and returns each as a finding
        assert len(findings) == 2
        assert findings[0]["severity"] == "high"
        assert findings[1]["id"] == "2"

    def test_parse_malformed_xml(self, adapter):
        xml_content = "<root><unclosed>"
        findings = adapter.parser._parse_xml(xml_content)
        assert findings == []  # Should return empty list on error
