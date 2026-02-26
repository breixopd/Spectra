"""Tests for UniversalParser (app/services/tools/adapter/parser.py)."""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from app.services.tools.adapter.parser import UniversalParser
from app.services.tools.models import OutputFormat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    fmt=OutputFormat.JSON,
    mapping=None,
    regex_patterns=None,
    llm_extraction=False,
    extraction_hint="",
    capture_stderr=True,
    combine_outputs=False,
    output_file_pattern=None,
):
    """Build a minimal mock ToolConfig with the given parsing attributes."""
    config = MagicMock()
    config.name = "test-tool"

    parsing = MagicMock()
    parsing.format = fmt
    parsing.mapping = mapping or {}
    parsing.regex_patterns = regex_patterns or []
    parsing.llm_extraction = llm_extraction
    parsing.extraction_hint = extraction_hint
    parsing.capture_stderr = capture_stderr
    parsing.combine_outputs = combine_outputs
    parsing.output_file_pattern = output_file_pattern

    config.parsing = parsing
    return config


# =====================================================================
# JSON parsing
# =====================================================================


class TestParseJson:
    def test_array_of_objects(self):
        config = _make_config(fmt=OutputFormat.JSON)
        parser = UniversalParser(config)

        data = [{"host": "1.2.3.4", "port": 80}, {"host": "5.6.7.8", "port": 443}]
        result = parser._parse_json(json.dumps(data))

        assert len(result) == 2
        assert result[0]["host"] == "1.2.3.4"
        assert result[1]["port"] == 443

    def test_single_object(self):
        config = _make_config(fmt=OutputFormat.JSON)
        parser = UniversalParser(config)

        data = {"name": "finding", "severity": "high"}
        result = parser._parse_json(json.dumps(data))

        assert len(result) == 1
        assert result[0]["severity"] == "high"

    def test_invalid_json_returns_empty(self):
        config = _make_config(fmt=OutputFormat.JSON)
        parser = UniversalParser(config)

        result = parser._parse_json("{not valid json!!!")
        assert result == []

    def test_primitive_value_wrapped(self):
        config = _make_config(fmt=OutputFormat.JSON)
        parser = UniversalParser(config)

        result = parser._parse_json('"just a string"')
        assert result == [{"value": "just a string"}]

    def test_array_filters_non_dict_items(self):
        config = _make_config(fmt=OutputFormat.JSON)
        parser = UniversalParser(config)

        data = [{"ok": True}, "skip me", 42, {"also": "ok"}]
        result = parser._parse_json(json.dumps(data))

        assert len(result) == 2
        assert result[0]["ok"] is True
        assert result[1]["also"] == "ok"

    def test_json_with_mapping(self):
        mapping = {"ip_address": "host", "port_number": "port"}
        config = _make_config(fmt=OutputFormat.JSON, mapping=mapping)
        parser = UniversalParser(config)

        data = {"host": "10.0.0.1", "port": 22, "extra": "data"}
        result = parser._parse_json(json.dumps(data))

        assert len(result) == 1
        assert result[0]["ip_address"] == "10.0.0.1"
        assert result[0]["port_number"] == 22
        assert result[0]["extra"] == "data"


# =====================================================================
# NDJSON parsing
# =====================================================================


class TestParseNdjson:
    def test_multiple_lines(self):
        config = _make_config(fmt=OutputFormat.NDJSON)
        parser = UniversalParser(config)

        lines = '{"a": 1}\n{"b": 2}\n{"c": 3}\n'
        result = parser._parse_ndjson(lines)

        assert len(result) == 3
        assert result[0]["a"] == 1
        assert result[2]["c"] == 3

    def test_mixed_valid_invalid(self):
        config = _make_config(fmt=OutputFormat.NDJSON)
        parser = UniversalParser(config)

        lines = '{"good": true}\nBAD LINE\n{"also": "good"}\n'
        result = parser._parse_ndjson(lines)

        assert len(result) == 2
        assert result[0]["good"] is True
        assert result[1]["also"] == "good"

    def test_empty_lines_skipped(self):
        config = _make_config(fmt=OutputFormat.NDJSON)
        parser = UniversalParser(config)

        lines = '\n{"a": 1}\n\n\n{"b": 2}\n'
        result = parser._parse_ndjson(lines)

        assert len(result) == 2

    def test_non_dict_json_skipped(self):
        config = _make_config(fmt=OutputFormat.NDJSON)
        parser = UniversalParser(config)

        lines = '"just a string"\n[1,2,3]\n{"ok": true}\n'
        result = parser._parse_ndjson(lines)

        assert len(result) == 1
        assert result[0]["ok"] is True

    def test_ndjson_with_mapping(self):
        mapping = {"target": "host"}
        config = _make_config(fmt=OutputFormat.NDJSON, mapping=mapping)
        parser = UniversalParser(config)

        lines = '{"host": "example.com", "port": 80}\n'
        result = parser._parse_ndjson(lines)

        assert result[0]["target"] == "example.com"
        assert result[0]["port"] == 80


# =====================================================================
# CSV parsing
# =====================================================================


class TestParseCsv:
    def test_csv_with_headers(self):
        config = _make_config(fmt=OutputFormat.CSV)
        parser = UniversalParser(config)

        csv_data = "host,port,service\n10.0.0.1,80,http\n10.0.0.2,443,https\n"
        result = parser._parse_csv(csv_data)

        assert len(result) == 2
        assert result[0]["host"] == "10.0.0.1"
        assert result[0]["port"] == "80"
        assert result[1]["service"] == "https"

    def test_csv_with_mapping(self):
        mapping = {"ip_address": "host"}
        config = _make_config(fmt=OutputFormat.CSV, mapping=mapping)
        parser = UniversalParser(config)

        csv_data = "host,port\n1.2.3.4,22\n"
        result = parser._parse_csv(csv_data)

        assert len(result) == 1
        assert result[0]["ip_address"] == "1.2.3.4"
        assert result[0]["port"] == "22"

    def test_csv_single_row(self):
        config = _make_config(fmt=OutputFormat.CSV)
        parser = UniversalParser(config)

        csv_data = "name,value\nalpha,100\n"
        result = parser._parse_csv(csv_data)

        assert len(result) == 1
        assert result[0]["name"] == "alpha"


# =====================================================================
# XML parsing
# =====================================================================


class TestParseXml:
    def test_generic_elements(self):
        config = _make_config(fmt=OutputFormat.XML)
        parser = UniversalParser(config)

        xml_data = """<root>
            <item>
                <id>1</id>
                <severity>high</severity>
            </item>
            <item>
                <id>2</id>
                <severity>low</severity>
            </item>
        </root>"""

        result = parser._parse_xml(xml_data)

        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[0]["severity"] == "high"
        assert result[1]["id"] == "2"

    def test_nmap_xml(self):
        config = _make_config(fmt=OutputFormat.XML)
        parser = UniversalParser(config)

        xml_data = """<?xml version="1.0"?>
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

        result = parser._parse_xml(xml_data)

        assert len(result) == 1
        assert result[0]["portid"] == "80"
        assert result[0]["service"] == "http"
        assert result[0]["product"] == "Apache"
        assert result[0]["ip"] == "192.168.1.1"

    def test_malformed_xml_returns_empty(self):
        config = _make_config(fmt=OutputFormat.XML)
        parser = UniversalParser(config)

        result = parser._parse_xml("<root><unclosed>")
        assert result == []

    def test_xml_attributes_extracted(self):
        config = _make_config(fmt=OutputFormat.XML)
        parser = UniversalParser(config)

        xml_data = '<root><result id="42" status="ok"/></root>'
        result = parser._parse_xml(xml_data)

        assert len(result) >= 1
        found = False
        for r in result:
            if r.get("id") == "42":
                assert r["status"] == "ok"
                found = True
        assert found

    def test_xml_with_mapping(self):
        mapping = {"vuln_id": "id", "risk": "severity"}
        config = _make_config(fmt=OutputFormat.XML, mapping=mapping)
        parser = UniversalParser(config)

        xml_data = """<root>
            <item><id>CVE-2024-0001</id><severity>critical</severity></item>
        </root>"""
        result = parser._parse_xml(xml_data)

        assert len(result) == 1
        assert result[0]["vuln_id"] == "CVE-2024-0001"
        assert result[0]["risk"] == "critical"

    def test_xml_no_known_containers_falls_back_to_root(self):
        config = _make_config(fmt=OutputFormat.XML)
        parser = UniversalParser(config)

        xml_data = "<data><custom_tag>value</custom_tag></data>"
        result = parser._parse_xml(xml_data)

        assert len(result) >= 1
        assert result[0].get("custom_tag") == "value"

    def test_nmap_xml_with_mapping(self):
        mapping = {"ip_address": "ip", "port_number": "portid"}
        config = _make_config(fmt=OutputFormat.XML, mapping=mapping)
        parser = UniversalParser(config)

        xml_data = """<?xml version="1.0"?>
        <nmaprun>
            <host>
                <address addr="10.0.0.5" addrtype="ipv4"/>
                <ports>
                    <port protocol="tcp" portid="443">
                        <state state="open"/>
                        <service name="https"/>
                    </port>
                </ports>
            </host>
        </nmaprun>"""

        result = parser._parse_xml(xml_data)
        assert len(result) == 1
        assert result[0]["ip_address"] == "10.0.0.5"
        assert result[0]["port_number"] == "443"


# =====================================================================
# Regex pattern parsing
# =====================================================================


class TestParseWithRegex:
    def test_named_groups(self):
        patterns = [{"pattern": r"(?P<host>\d+\.\d+\.\d+\.\d+):(?P<port>\d+)"}]
        config = _make_config(fmt=OutputFormat.TEXT, regex_patterns=patterns)
        parser = UniversalParser(config)

        output = "Found service at 10.0.0.1:80 and 10.0.0.2:443"
        result = parser._parse_with_regex(output)

        assert len(result) == 2
        assert result[0]["host"] == "10.0.0.1"
        assert result[0]["port"] == "80"
        assert result[1]["host"] == "10.0.0.2"
        assert result[1]["port"] == "443"

    def test_pattern_with_type(self):
        patterns = [
            {
                "pattern": r"(?P<name>\w+)\s+is\s+(?P<status>\w+)",
                "type": "service",
            }
        ]
        config = _make_config(fmt=OutputFormat.TEXT, regex_patterns=patterns)
        parser = UniversalParser(config)

        output = "httpd is running\nnginx is stopped"
        result = parser._parse_with_regex(output)

        assert len(result) == 2
        assert result[0]["_type"] == "service"
        assert result[0]["name"] == "httpd"
        assert result[1]["status"] == "stopped"

    def test_no_matches_returns_empty(self):
        patterns = [{"pattern": r"(?P<cve>CVE-\d{4}-\d+)"}]
        config = _make_config(fmt=OutputFormat.TEXT, regex_patterns=patterns)
        parser = UniversalParser(config)

        result = parser._parse_with_regex("no cves here")
        assert result == []

    def test_invalid_regex_skipped(self):
        patterns = [
            {"pattern": r"[invalid(regex"},
            {"pattern": r"(?P<word>\w+)"},
        ]
        config = _make_config(fmt=OutputFormat.TEXT, regex_patterns=patterns)
        parser = UniversalParser(config)

        result = parser._parse_with_regex("hello")
        assert len(result) == 1
        assert result[0]["word"] == "hello"

    def test_missing_pattern_key_skipped(self):
        patterns = [
            {"not_pattern": "something"},
            {"pattern": r"(?P<val>\d+)"},
        ]
        config = _make_config(fmt=OutputFormat.TEXT, regex_patterns=patterns)
        parser = UniversalParser(config)

        result = parser._parse_with_regex("value is 42")
        assert len(result) == 1
        assert result[0]["val"] == "42"

    def test_regex_with_mapping(self):
        patterns = [{"pattern": r"(?P<addr>\d+\.\d+\.\d+\.\d+)"}]
        mapping = {"ip_address": "addr"}
        config = _make_config(
            fmt=OutputFormat.TEXT, regex_patterns=patterns, mapping=mapping
        )
        parser = UniversalParser(config)

        result = parser._parse_with_regex("scan 10.0.0.1")
        assert len(result) == 1
        assert result[0]["ip_address"] == "10.0.0.1"


# =====================================================================
# Field mapping (_apply_mapping)
# =====================================================================


class TestApplyMapping:
    def test_mapped_fields(self):
        mapping = {"ip_address": "host", "port_number": "port"}
        config = _make_config(mapping=mapping)
        parser = UniversalParser(config)

        data = {"host": "10.0.0.1", "port": 80, "extra": "info"}
        result = parser._apply_mapping(data)

        assert result["ip_address"] == "10.0.0.1"
        assert result["port_number"] == 80

    def test_unmapped_fields_pass_through(self):
        mapping = {"ip_address": "host"}
        config = _make_config(mapping=mapping)
        parser = UniversalParser(config)

        data = {"host": "10.0.0.1", "service": "http", "version": "2.0"}
        result = parser._apply_mapping(data)

        assert result["ip_address"] == "10.0.0.1"
        assert result["service"] == "http"
        assert result["version"] == "2.0"
        assert "host" not in result

    def test_no_mapping_returns_data_unchanged(self):
        config = _make_config(mapping={})
        parser = UniversalParser(config)

        data = {"a": 1, "b": 2}
        result = parser._apply_mapping(data)
        assert result == {"a": 1, "b": 2}

    def test_non_dict_wrapped(self):
        config = _make_config(mapping={"x": "y"})
        parser = UniversalParser(config)

        result = parser._apply_mapping("not a dict")
        assert result == {"value": "not a dict"}

    def test_mapping_source_field_absent(self):
        mapping = {"ip_address": "host", "port_number": "port"}
        config = _make_config(mapping=mapping)
        parser = UniversalParser(config)

        data = {"host": "10.0.0.1", "other": "val"}
        result = parser._apply_mapping(data)

        assert result["ip_address"] == "10.0.0.1"
        assert "port_number" not in result
        assert result["other"] == "val"


# =====================================================================
# Output collection (_collect_output_content)
# =====================================================================


class TestCollectOutputContent:
    def test_stdout_only(self):
        config = _make_config()
        parser = UniversalParser(config)

        result = parser._collect_output_content("some stdout", None)
        assert result == ["some stdout"]

    def test_empty_stdout_no_file(self):
        config = _make_config()
        parser = UniversalParser(config)

        result = parser._collect_output_content("   ", None)
        assert result == []

    def test_file_reading(self, tmp_path):
        config = _make_config()
        parser = UniversalParser(config)

        output_file = tmp_path / "output.json"
        output_file.write_text('{"result": true}')

        result = parser._collect_output_content("", str(output_file))
        assert len(result) == 1
        assert '{"result": true}' in result[0]

    def test_file_and_stdout_combined(self, tmp_path):
        config = _make_config(combine_outputs=True)
        config.parsing.combine_outputs = True
        parser = UniversalParser(config)

        output_file = tmp_path / "output.txt"
        output_file.write_text("file content")

        result = parser._collect_output_content("stdout content", str(output_file))
        assert len(result) == 2
        assert "file content" in result[0]
        assert "stdout content" in result[1]

    def test_directory_output(self, tmp_path):
        config = _make_config()
        parser = UniversalParser(config)

        sub = tmp_path / "results"
        sub.mkdir()
        (sub / "a.txt").write_text("file a")
        (sub / "b.txt").write_text("file b")

        result = parser._collect_output_content("", str(sub))
        assert len(result) == 2

    def test_nonexistent_file_falls_back_to_stdout(self):
        config = _make_config()
        parser = UniversalParser(config)

        result = parser._collect_output_content(
            "fallback stdout", "/tmp/nonexistent_file_xyz_123"
        )
        assert result == ["fallback stdout"]

    def test_output_file_pattern(self, tmp_path):
        config = _make_config(output_file_pattern="*.json")
        config.parsing.output_file_pattern = "*.json"
        parser = UniversalParser(config)

        (tmp_path / "result1.json").write_text('{"a":1}')
        (tmp_path / "result2.json").write_text('{"b":2}')
        (tmp_path / "ignore.txt").write_text("not this")

        output_file = str(tmp_path / "result1.json")
        result = parser._collect_output_content("", output_file)

        assert len(result) == 2
        contents = " ".join(result)
        assert '"a"' in contents or '"b"' in contents


# =====================================================================
# parse_output (async entry point)
# =====================================================================


class TestParseOutput:
    @pytest.mark.asyncio
    async def test_json_end_to_end(self):
        config = _make_config(fmt=OutputFormat.JSON)
        parser = UniversalParser(config)

        data = [{"host": "10.0.0.1", "port": 80}]
        result = await parser.parse_output(json.dumps(data), "", None)

        assert len(result) == 1
        assert result[0]["host"] == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_empty_output_returns_empty(self):
        config = _make_config(fmt=OutputFormat.JSON)
        parser = UniversalParser(config)

        result = await parser.parse_output("", "", None)
        assert result == []

    @pytest.mark.asyncio
    async def test_stderr_captured_for_text_format(self):
        config = _make_config(fmt=OutputFormat.TEXT, capture_stderr=True)
        parser = UniversalParser(config)

        result = await parser.parse_output("", "error output here", None)

        assert len(result) == 1
        assert "error output here" in result[0].get("raw_output", "")

    @pytest.mark.asyncio
    async def test_stderr_not_captured_when_disabled(self):
        config = _make_config(fmt=OutputFormat.TEXT, capture_stderr=False)
        parser = UniversalParser(config)

        result = await parser.parse_output("", "error output here", None)
        assert result == []

    @pytest.mark.asyncio
    async def test_text_fallback_returns_raw_output(self):
        config = _make_config(fmt=OutputFormat.TEXT)
        parser = UniversalParser(config)

        result = await parser.parse_output("plain text output", "", None)

        assert len(result) == 1
        assert result[0]["raw_output"] == "plain text output"

    @pytest.mark.asyncio
    async def test_text_with_regex_patterns(self):
        patterns = [{"pattern": r"(?P<ip>\d+\.\d+\.\d+\.\d+)"}]
        config = _make_config(fmt=OutputFormat.TEXT, regex_patterns=patterns)
        parser = UniversalParser(config)

        result = await parser.parse_output("host at 10.0.0.1", "", None)

        assert len(result) == 1
        assert result[0]["ip"] == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_csv_end_to_end(self):
        config = _make_config(fmt=OutputFormat.CSV)
        parser = UniversalParser(config)

        csv_data = "host,port\n10.0.0.1,80\n10.0.0.2,443\n"
        result = await parser.parse_output(csv_data, "", None)

        assert len(result) == 2
        assert result[0]["host"] == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_ndjson_end_to_end(self):
        config = _make_config(fmt=OutputFormat.NDJSON)
        parser = UniversalParser(config)

        ndjson = '{"x": 1}\n{"x": 2}\n'
        result = await parser.parse_output(ndjson, "", None)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_xml_end_to_end(self):
        config = _make_config(fmt=OutputFormat.XML)
        parser = UniversalParser(config)

        xml_data = "<root><item><name>test</name></item></root>"
        result = await parser.parse_output(xml_data, "", None)

        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_file_output(self, tmp_path):
        config = _make_config(fmt=OutputFormat.JSON)
        parser = UniversalParser(config)

        output_file = tmp_path / "out.json"
        output_file.write_text('[{"found": true}]')

        result = await parser.parse_output("", "", str(output_file))

        assert len(result) == 1
        assert result[0]["found"] is True

    @pytest.mark.asyncio
    async def test_whitespace_only_output(self):
        config = _make_config(fmt=OutputFormat.JSON)
        parser = UniversalParser(config)

        result = await parser.parse_output("   \n\t  ", "", None)
        assert result == []


# =====================================================================
# LLM parsing stub
# =====================================================================


class TestParseWithLlm:
    @pytest.mark.asyncio
    async def test_no_llm_client_returns_empty(self):
        config = _make_config(fmt=OutputFormat.TEXT, llm_extraction=True)
        parser = UniversalParser(config, llm_client=None)

        result = await parser._parse_with_llm("some output")
        assert result == []
