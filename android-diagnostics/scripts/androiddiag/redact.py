"""Replace personal identifiers in report text with stable hashed placeholders.

Phone dumps carry MAC addresses (the phone's own, its peers', the access
points'), IP addresses, network names, serial numbers, e-mail addresses and
phone numbers. A shared report needs none of them, but it should still show
that two lines mention the same device. Each value therefore becomes
``<kind:hash>``, where the hash is the first hex digits of SHA-256 over an
optional salt, the kind and the normalised value. The same value gives the
same placeholder everywhere in one report, and in every report made with the
same salt.

Network names and serial numbers have no fixed shape. They are recognised by
their context (``SSID: "..."``, ``ro.serialno``), remembered by
:meth:`Redactor.learn`, and then replaced wherever else they appear. A name
of one or two characters is too likely to be an ordinary word, so it is
replaced elsewhere only between quotes; its explicit contexts (``SSID: "A"``,
``configKey="AB"WPA_PSK``) are always hidden.

Limitations: phone numbers are recognised only in international ``+`` form
or as ``tel:`` URIs, and a dotted version string with four numbers looks like
an IPv4 address and is redacted too.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Hex digits kept from the hash: 4 give 65,536 values, enough to keep the
# handful of devices in one report apart while revealing little.
HASH_DIGITS = 4
# Learned literals shorter than this are replaced only between quotes.
MIN_LEARNED_LEN = 3
# Values that look like an SSID or serial in context but name nothing.
_NOT_NAMES = frozenset(
    {
        "",
        "<unknown ssid>",
        "unknown",
        "null",
        "none",
        "<none>",
        "any",
        "n/a",
        "true",
        "false",
    },
)

_PLACEHOLDER = r"<[a-z]+:[0-9a-f]+>"
_PLACEHOLDER_RE = re.compile(_PLACEHOLDER)
# A local part and a domain starting with a letter keep HAL versions
# (``sensors@2.0-service``) and job tags (``@com.example.app``) intact.
_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9._%+-]+@"
    r"[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b",
)
_MAC_RE = re.compile(
    r"(?<![\w:-])[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}(?![\w:-])",
)
_IPV6_RE = re.compile(
    r"(?<![\w:.])([0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?:\.\d{1,3}){0,3})"
    r"(%[\w.]+)?(?![\w:])",
)
_IPV4_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?!\w|\.\d)")
_PHONE_RE = re.compile(r"(?<![\w+])(?:tel:)?\+\d{1,3}(?:[ -]?\d){6,13}(?![\d])")
_TEL_RE = re.compile(r"\btel:\d[\d-]{4,}\d")
# 15 to 20 digits: IMEI and IMSI (15), ICCID (19-20). A leading minus marks
# a signed counter or hash, not an identifier.
_LONG_ID_RE = re.compile(r"(?<![\w.-])\d{15,20}(?![\w.])")
# Sentinels that dumps print for 'unset' or 'no limit': Long.MAX_VALUE, one
# below it, the magnitude of Long.MIN_VALUE, and 2^64 - 1.
_SENTINEL_NUMBERS = frozenset(
    {
        "9223372036854775807",
        "9223372036854775806",
        "9223372036854775808",
        "18446744073709551615",
    },
)
_SSID_RE = re.compile(
    r"(?i)(?<!<)\b(?:ssid|wifiNetworkKey|networkKey|wifi_network_key|network name)"
    r"[\"']?\s*[=:]\s*"
    rf"(?![\"\[]?{_PLACEHOLDER})"
    r"(?:\"(?P<quoted>[^\"\n]{1,64})\"|(?P<bare>[^\s\"'<,;)\]}][^\s\"',;)\]}]{0,63}))",
)
_CONFIG_KEY_RE = re.compile(
    rf"\"(?!{_PLACEHOLDER}\")(?P<ssid>[^\"\n]{{1,64}})\"-?"
    r"(?:WPA_PSK|WPA_EAP|SAE|OWE|WEP|NONE|IEEE8021X|SUITE_B_192|WAPI_PSK)\b",
)
_SERIAL_RE = re.compile(
    r"(?i)(?<!<)\b(?:ro\.(?:boot\.)?serialno|androidboot\.serialno"
    r"|serial ?(?:no|number)?)"
    r"\]?\s*[=:]\s*\[?[\"']?"
    rf"(?![\"\[]?{_PLACEHOLDER})"
    r"(?P<serial>[A-Za-z0-9]{6,20})\b",
)


def _keep_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Loopback, unspecified, multicast and netmask-like addresses name nobody."""
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        return True
    return isinstance(ip, ipaddress.IPv4Address) and str(ip).startswith("255.")


class Redactor:
    """Replace identifiers with ``<kind:hash>`` placeholders, consistently."""

    def __init__(self, salt: str = "", digits: int = HASH_DIGITS) -> None:
        """Hash with ``salt`` and keep ``digits`` hex digits per placeholder."""
        self.salt = salt
        self.digits = digits
        self.known: dict[str, str] = {}
        self.counts: Counter[str] = Counter()
        self._known_re: re.Pattern[str] | None = None

    def placeholder(self, kind: str, value: str) -> str:
        """Return the placeholder for a normalised ``value`` of ``kind``."""
        digest = hashlib.sha256(f"{self.salt}\0{kind}\0{value}".encode()).hexdigest()
        self.counts[kind] += 1
        return f"<{kind}:{digest[: self.digits]}>"

    def learn(self, text: str) -> None:
        """Remember network names and serial numbers found in their context."""
        before = len(self.known)
        for m in _SSID_RE.finditer(text):
            value = m["quoted"] if m["quoted"] is not None else m["bare"]
            self._remember(value, "ssid")
        for m in _CONFIG_KEY_RE.finditer(text):
            self._remember(m["ssid"], "ssid")
        for m in _SERIAL_RE.finditer(text):
            self._remember(m["serial"], "serial")
        if len(self.known) != before:
            self._known_re = None

    def _remember(self, value: str, kind: str) -> None:
        value = value.strip()
        if _PLACEHOLDER_RE.fullmatch(value):
            return
        if value and value.lower() not in _NOT_NAMES:
            self.known.setdefault(value, kind)

    def redact(self, text: str) -> str:
        """Return ``text`` with every recognised identifier replaced."""
        self.learn(text)
        text = self._replace_known(text)
        for pattern, func in self._rules():
            text = pattern.sub(func, text)
        return text

    def redact_obj(self, obj: object) -> object:
        """Redact every string inside nested lists and dicts (keys are kept)."""
        self.learn_obj(obj)
        return self._redact_obj(obj)

    def learn_obj(self, obj: object) -> None:
        """Learn from every string value inside nested lists and dicts.

        Use this rather than learning from a JSON dump: JSON escapes the
        quotes of ``SSID: "name"``, so the context would not match.
        """
        if isinstance(obj, str):
            self.learn(obj)
        elif isinstance(obj, dict):
            for value in obj.values():
                self.learn_obj(value)
        elif isinstance(obj, list | tuple):
            for value in obj:
                self.learn_obj(value)

    def _redact_obj(self, obj: object) -> object:
        if isinstance(obj, str):
            return self.redact(obj)
        if isinstance(obj, dict):
            return {key: self._redact_obj(value) for key, value in obj.items()}
        if isinstance(obj, list | tuple):
            return [self._redact_obj(value) for value in obj]
        return obj

    def _replace_known(self, text: str) -> str:
        if not self.known:
            return text
        if self._known_re is None:
            names = sorted(self.known, key=len, reverse=True)
            long = [re.escape(n) for n in names if len(n) >= MIN_LEARNED_LEN]
            short = [re.escape(n) for n in names if len(n) < MIN_LEARNED_LEN]
            alternatives = []
            if long:
                alternatives.append(rf"(?<!\w)(?:{'|'.join(long)})(?!\w)")
            if short:
                alternatives.append(rf"(?<=[\"'])(?:{'|'.join(short)})(?=[\"'])")
            self._known_re = re.compile("|".join(alternatives))
        return self._known_re.sub(
            lambda m: self.placeholder(self.known[m[0]], m[0]),
            text,
        )

    def _rules(self) -> list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]]:
        return [
            (_EMAIL_RE, lambda m: self.placeholder("email", m[0].lower())),
            (_MAC_RE, self._mac),
            (_IPV6_RE, self._ipv6),
            (_IPV4_RE, self._ipv4),
            (_PHONE_RE, self._phone),
            (_TEL_RE, self._phone),
            (_LONG_ID_RE, self._long_id),
            (_SSID_RE, self._ssid_in_context),
            (_CONFIG_KEY_RE, self._config_key),
            (_SERIAL_RE, self._serial_in_context),
        ]

    def _mac(self, m: re.Match[str]) -> str:
        return self.placeholder("mac", m[0].lower().replace("-", ":"))

    def _ipv6(self, m: re.Match[str]) -> str:
        try:
            ip = ipaddress.IPv6Address(m[1])
        except ValueError:
            return m[0]
        if _keep_ip(ip):
            return m[0]
        return self.placeholder("ip", ip.compressed) + (m[2] or "")

    def _ipv4(self, m: re.Match[str]) -> str:
        try:
            ip = ipaddress.IPv4Address(m[1])
        except ValueError:
            return m[0]
        return m[0] if _keep_ip(ip) else self.placeholder("ip", str(ip))

    def _long_id(self, m: re.Match[str]) -> str:
        return m[0] if m[0] in _SENTINEL_NUMBERS else self.placeholder("id", m[0])

    def _phone(self, m: re.Match[str]) -> str:
        return self.placeholder("phone", re.sub(r"\D", "", m[0]))

    def _ssid_in_context(self, m: re.Match[str]) -> str:
        group = "quoted" if m["quoted"] is not None else "bare"
        return self._hide_group(m, group, "ssid")

    def _config_key(self, m: re.Match[str]) -> str:
        return self._hide_group(m, "ssid", "ssid")

    def _serial_in_context(self, m: re.Match[str]) -> str:
        return self._hide_group(m, "serial", "serial")

    def _hide_group(self, m: re.Match[str], group: str, kind: str) -> str:
        """Return the match with only ``group`` replaced by a placeholder."""
        if m[group].strip().lower() in _NOT_NAMES:
            return m[0]
        start, end = m.span(group)
        offset = m.start()
        hidden = self.placeholder(kind, m[group].strip())
        return m[0][: start - offset] + hidden + m[0][end - offset :]
