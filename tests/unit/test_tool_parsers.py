import pytest
import xml.etree.ElementTree as ET
from app.services.tools.parsers import xml_to_dict, parse_nmap_xml

def test_xml_to_dict_simple():
    xml = "<root><child key='val'>text</child></root>"
    root = ET.fromstring(xml)
    expected = {
        "child": {
            "key": "val",
            "_text": "text"
        }
    }
    assert xml_to_dict(root) == expected

def test_xml_to_dict_list():
    xml = """
    <root>
        <item>1</item>
        <item>2</item>
    </root>
    """
    root = ET.fromstring(xml)
    result = xml_to_dict(root)
    assert isinstance(result["item"], list)
    assert len(result["item"]) == 2
    assert result["item"][0]["_text"] == "1"
    assert result["item"][1]["_text"] == "2"

def test_parse_nmap_xml():
    xml = """
    <nmaprun>
        <host>
            <status state="up"/>
            <address addr="127.0.0.1" addrtype="ipv4"/>
            <ports>
                <port protocol="tcp" portid="80">
                    <state state="open" reason="syn-ack" reason_ttl="0"/>
                    <service name="http" product="nginx" version="1.18.0" method="table" conf="3"/>
                </port>
                <port protocol="tcp" portid="443">
                    <state state="closed" reason="reset" reason_ttl="0"/>
                </port>
            </ports>
        </host>
        <host>
            <status state="up"/>
            <address addr="10.0.0.1" addrtype="ipv4"/>
            <ports>
                <port protocol="tcp" portid="22">
                    <state state="open" reason="syn-ack" reason_ttl="0"/>
                    <service name="ssh" method="table" conf="3"/>
                </port>
            </ports>
        </host>
    </nmaprun>
    """
    root = ET.fromstring(xml)
    findings = parse_nmap_xml(root)
    
    assert len(findings) == 2
    
    # Check first finding (port 80 open)
    f1 = findings[0]
    assert f1["ip"] == "127.0.0.1"
    assert f1["portid"] == "80"
    assert f1["service"] == "http"
    assert f1["product"] == "nginx"
    
    # Check second finding (port 22 open)
    f2 = findings[1]
    assert f2["ip"] == "10.0.0.1"
    assert f2["portid"] == "22"
    assert f2["service"] == "ssh"
    assert f2["product"] is None
