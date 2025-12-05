import pytest
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock
from app.services.tools.adapter import CommandToolAdapter
from app.services.tools.models import ToolConfig, OutputFormat

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
        
        # _parse_xml returns [root_dict]
        assert len(findings) == 1
        # The items are nested under result['item'] if root name is stripped or under root?
        # Check _xml_to_dict logic: it returns children keys. So keys are 'item'.
        items = findings[0]['item']
        assert len(items) == 2
        assert items[0]["severity"]["_text"] == "high"
        assert items[1]["id"]["_text"] == "2"

    def test_parse_malformed_xml(self, adapter):
        xml_content = "<root><unclosed>"
        findings = adapter.parser._parse_xml(xml_content)
        assert findings == []  # Should return empty list on error
