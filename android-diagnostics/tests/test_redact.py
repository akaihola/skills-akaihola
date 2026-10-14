"""Tests for androiddiag.redact: hashed placeholders for personal identifiers.

All addresses and names are invented: documentation IP ranges (192.0.2.0/24,
198.51.100.0/24, 2001:db8::/32), locally administered MACs (02:00:00:...),
example.com addresses and the network name ExampleNet.
"""

from __future__ import annotations

import re
from textwrap import dedent

import pytest
from androiddiag.redact import Redactor

PLACEHOLDER = re.compile(r"<(\w+):[0-9a-f]{4}>")


def kinds(text):
    return [m[1] for m in PLACEHOLDER.finditer(text)]


def test_mac_separators_and_case_give_one_placeholder():
    r = Redactor()
    out = r.redact("wlan 02:00:00:aa:bb:01 bssid 02-00-00-AA-BB-01")
    first, second = re.findall(r"<mac:\w+>", out)
    assert first == second
    assert "02:00" not in out


@pytest.mark.parametrize(
    "text",
    [
        "peer 192.0.2.17:443",
        "route 198.51.100.0/24 dev wlan0",
        "(192.0.2.1)",
    ],
)
def test_ipv4_is_redacted(text):
    out = Redactor().redact(text)
    assert kinds(out) == ["ip"]
    assert not re.search(r"\d+\.\d+\.\d+\.\d+", out)


@pytest.mark.parametrize(
    "text",
    [
        "loopback 127.0.0.1",
        "any 0.0.0.0",
        "mask 255.255.255.0",
        "mdns 224.0.0.251",
        "kernel 5.10.217-example9",
        "build TEST.1.0.15",
        "time 12:24:00.799 and 1:02:03",
        "v6 ::1 and ff02::fb and ::",
        "C++ Class::member and std::string",
    ],
)
def test_harmless_values_stay(text):
    assert Redactor().redact(text) == text


def test_ipv6_with_zone_and_link_local():
    out = Redactor().redact("addr 2001:db8::1%wlan0 and fe80::200:ff:fe00:1/64")
    assert out.startswith("addr <ip:")
    assert "%wlan0" in out
    assert out.endswith("/64")
    assert kinds(out) == ["ip", "ip"]


def test_ipv6_spellings_share_a_placeholder():
    r = Redactor()
    out = r.redact("2001:db8:0:0:0:0:0:1 and 2001:db8::1")
    one, two = re.findall(r"<ip:\w+>", out)
    assert one == two


def test_emails_but_not_hal_or_job_names():
    out = Redactor().redact(
        "mail owner@example.com and first.last+tag@mail.example.org; "
        "hal vendor.sensors@2.0-service.example and job @com.example.app",
    )
    assert kinds(out) == ["email", "email"]
    assert "sensors@2.0-service.example" in out
    assert "@com.example.app" in out


@pytest.mark.parametrize(
    "prefix",
    ["com", "org", "net", "io", "de", "android", "androidx", "vendor"],
)
@pytest.mark.parametrize("domain", ["example.com", "example.org"])
def test_email_domain_prefixes(prefix, domain):
    address = f"sender@{prefix}.{domain}"
    r = Redactor()
    expected = r.placeholder("email", address)
    out = r.redact(f"{address} {address.upper()}")
    assert out == f"{expected} {expected}"
    assert r.redact(out) == out


def test_phone_numbers_and_long_ids():
    out = Redactor().redact(
        "call +1 555 0100 123 or tel:5550100123; id 356789012345678 count 3345750",
    )
    assert kinds(out) == ["phone", "phone", "id"]
    assert "3345750" in out


def test_network_names_are_learned_from_context():
    text = dedent(
        """\
        SSID: "ExampleNet", BSSID: 02:00:00:00:00:01
        ssid=ExampleNet2 wifiNetworkKey="Example Net"
        configKey="OtherNet"WPA_PSK
        roamed on ExampleNet again; OtherNet and Example Net too
        SSID: <unknown ssid>
        """,
    )
    r = Redactor()
    out = r.redact(text)
    for name in ("ExampleNet", "ExampleNet2", "Example Net", "OtherNet"):
        assert name not in out
    assert "SSID: <unknown ssid>" in out
    m = re.search(r'SSID: "(<ssid:\w+>)"', out)
    assert m
    first = m[1]
    assert f"roamed on {first} again" in out
    assert r.known["ExampleNet"] == "ssid"


def test_learning_from_one_text_redacts_another():
    r = Redactor()
    r.learn('ro.serialno]: [A1B2C3D4E5]\nSSID="ExampleNet"')
    out = r.redact("device A1B2C3D4E5 was on ExampleNet")
    assert kinds(out) == ["serial", "ssid"]


@pytest.mark.parametrize(
    "text",
    [
        "[ro.serialno]: [A1B2C3D4E5]",
        "androidboot.serialno=A1B2C3D4E5",
        "Serial number: A1B2C3D4E5",
        "serial=A1B2C3D4E5",
    ],
)
def test_serial_contexts(text):
    out = Redactor().redact(text)
    assert "A1B2C3D4E5" not in out
    assert kinds(out) == ["serial"]


def test_placeholders_are_stable_and_salted():
    text = "peer 192.0.2.17"
    assert Redactor().redact(text) == Redactor().redact(text)
    assert Redactor("one").redact(text) != Redactor("two").redact(text)


def test_redaction_is_idempotent():
    text = 'SSID: "ExampleNet" peer 192.0.2.17 mac 02:00:00:00:00:02 serial=A1B2C3D4E5'
    r = Redactor()
    once = r.redact(text)
    assert r.redact(once) == once


def test_redact_obj_keeps_keys_and_types():
    r = Redactor()
    obj = {
        "ip": "192.0.2.9",
        "rows": [{"mac": "02:00:00:00:00:03", "n": 3}, ("ssid=ExampleNet",)],
        "count": 1.5,
    }
    out = r.redact_obj(obj)
    assert isinstance(out, dict)
    assert set(out) == {"ip", "rows", "count"}
    assert out["count"] == pytest.approx(1.5)
    assert out["rows"][0]["n"] == 3
    assert kinds(out["ip"]) == ["ip"]
    assert kinds(out["rows"][0]["mac"]) == ["mac"]
    assert kinds(out["rows"][1][0]) == ["ssid"]
    assert r.counts == {"ip": 1, "mac": 1, "ssid": 1}


@pytest.mark.parametrize(
    "text",
    [
        "mMaximumScreenOffTimeout=9223372036854775807",  # Long.MAX_VALUE
        "nextAlarm=9223372036854775806",
        "min=-9223372036854775808",  # Long.MIN_VALUE
        "limit=18446744073709551615",  # 2^64 - 1
        "cache_key=-4711471147114711471",  # a signed hash
    ],
)
def test_sentinels_and_negative_numbers_are_not_ids(text):
    assert Redactor().redact(text) == text


def test_learn_obj_reads_string_values_not_json_text():
    """JSON would escape the quotes of SSID: "name" and hide the context."""
    r = Redactor()
    r.learn_obj({"rows": [{"line": 'SSID: "Example Home" rssi=-61'}], "n": 3})
    assert r.known == {"Example Home": "ssid"}
    assert kinds(r.redact("left Example Home")) == ["ssid"]
