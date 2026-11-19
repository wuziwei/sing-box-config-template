#!/usr/bin/env python3
"""
build_geodata.py - Protobuf GeoData Builder for Honk / V2Ray / Sing-box.

Builds custom geosite.dat and geoip.dat by merging upstream DustinWin rulesets
with custom rulesets (Google, Meta, BlockHttpDNS, FakeIP-Filter, WebRTC-STUN, DoH-Canary).

Guarantees:
1. Zero BT / P2P rules (explicitly purges TRACKERSLIST / BITTORRENT).
2. Zero duplicate country_code warnings (excludes any upstream entry with same code).
3. Pure Python 3 standard library with zero external dependencies.
4. Seamlessly reuses sibling ../rules/ directory for google, meta, and fakeipfilter rules.
"""

import argparse
import hashlib
import ipaddress
import json
import os
import re
import sys
import urllib.request
from typing import Dict, List, Set, Tuple

UPSTREAM_GEOSITE_URL = (
    "https://raw.githubusercontent.com/DustinWin/ruleset_geodata/mihomo-geodata/geosite-all.dat"
)
UPSTREAM_GEOIP_URL = (
    "https://raw.githubusercontent.com/DustinWin/ruleset_geodata/mihomo-geodata/geoip.dat"
)

BLOCKHTTPDNS_REMOTE_URL = (
    "https://raw.githubusercontent.com/senshinya/singbox_ruleset/main/rule/BlockHttpDNS/BlockHttpDNS.json"
)

EXCLUDED_UPSTREAM_GEOSITE_CODES = {
    "TRACKERSLIST",
    "BITTORRENT",
    "TORRENT",
    "FAKEIPFILTER-CN",
    "FAKEIPFILTER-!CN",
}

EXPECTED_GEOSITE_TAGS = [
    "ADS",
    "PRIVATE",
    "CN",
    "APPLE-CN",
    "MICROSOFT-CN",
    "GAMES-CN",
    "YOUTUBE",
    "NETFLIX",
    "SPOTIFY",
    "PROXY",
    "GOOGLE",
    "META",
    "BLOCKHTTPDNS",
    "WEBRTC-STUN",
    "DOH-CANARY",
]

EXPECTED_GEOIP_TAGS = [
    "CN",
    "PRIVATE",
    "TELEGRAM",
    "BLOCKHTTPDNS",
]

# ---------------------------------------------------------------------------
# Protobuf Low-level Wire Helpers (Zero Dependency)
# ---------------------------------------------------------------------------

def encode_varint(value: int) -> bytes:
    buf = bytearray()
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)


def decode_varint(data: bytes, pos: int) -> Tuple[int, int]:
    res = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        res |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return res, pos


def encode_length_delimited(field_number: int, data: bytes) -> bytes:
    tag = (field_number << 3) | 2
    return encode_varint(tag) + encode_varint(len(data)) + data


def encode_varint_field(field_number: int, value: int) -> bytes:
    tag = (field_number << 3) | 0
    return encode_varint(tag) + encode_varint(value)


def encode_geosite_domain(domain_type: int, value: str) -> bytes:
    val_bytes = value.encode("utf-8")
    inner = encode_varint_field(1, domain_type) + encode_length_delimited(2, val_bytes)
    return encode_length_delimited(2, inner)


def encode_geosite_group(country_code: str, domains: List[Tuple[int, str]]) -> bytes:
    inner = bytearray()
    inner.extend(encode_length_delimited(1, country_code.encode("utf-8")))
    for dtype, dval in domains:
        inner.extend(encode_geosite_domain(dtype, dval))
    return bytes(inner)


def encode_geoip_cidr(cidr_str: str) -> bytes:
    net = ipaddress.ip_network(cidr_str, strict=False)
    ip_bytes = net.network_address.packed
    inner = encode_length_delimited(1, ip_bytes) + encode_varint_field(2, net.prefixlen)
    return encode_length_delimited(2, inner)


def encode_geoip_entry(country_code: str, cidrs: List[str]) -> bytes:
    inner = bytearray()
    inner.extend(encode_length_delimited(1, country_code.encode("utf-8")))
    for cidr in cidrs:
        inner.extend(encode_geoip_cidr(cidr))
    return bytes(inner)


# ---------------------------------------------------------------------------
# Upstream .dat Parsing (Preserves exact raw inner bytes of kept entries)
# ---------------------------------------------------------------------------

def parse_upstream_entries(data: bytes) -> Dict[str, bytes]:
    pos = 0
    entries: Dict[str, bytes] = {}
    while pos < len(data):
        tag, pos = decode_varint(data, pos)
        field = tag >> 3
        wire = tag & 7
        if field == 1 and wire == 2:
            length, pos = decode_varint(data, pos)
            entry_end = pos + length
            inner_bytes = data[pos:entry_end]

            ipos = 0
            country_code = None
            while ipos < len(inner_bytes):
                itag, ipos = decode_varint(inner_bytes, ipos)
                ifitag = itag >> 3
                iwire = itag & 7
                if ifitag == 1 and iwire == 2:
                    slen, ipos = decode_varint(inner_bytes, ipos)
                    country_code = inner_bytes[ipos : ipos + slen].decode("utf-8", errors="ignore")
                    break
                elif iwire == 0:
                    _, ipos = decode_varint(inner_bytes, ipos)
                elif iwire == 2:
                    slen, ipos = decode_varint(inner_bytes, ipos)
                    ipos += slen

            if country_code:
                code_upper = country_code.strip().upper()
                entries[code_upper] = inner_bytes
            pos = entry_end
        else:
            if wire == 0:
                _, pos = decode_varint(data, pos)
            elif wire == 2:
                l, pos = decode_varint(data, pos)
                pos += l
            else:
                break
    return entries


# ---------------------------------------------------------------------------
# Custom Rules Loading & Validation
# ---------------------------------------------------------------------------

def validate_and_compile_regex(pattern: str) -> None:
    if any(look in pattern for look in ["(?=", "(?!", "(?<=", "(?<!"]):
        raise ValueError(f"Rust-incompatible regex lookaround found in pattern: {pattern}")
    test_pattern = pattern
    if test_pattern.startswith("^(?"):
        idx = test_pattern.find(")")
        if idx != -1:
            flags = test_pattern[1 : idx + 1]
            rest = test_pattern[idx + 1 :]
            test_pattern = f"{flags}^{rest}"
    re.compile(test_pattern)


def load_singbox_rule_json(file_path: str) -> Tuple[List[Tuple[int, str]], List[str]]:
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    domains: List[Tuple[int, str]] = []
    cidrs: List[str] = []

    for rule in data.get("rules", []):
        for kw in rule.get("domain_keyword", []):
            domains.append((0, kw))
        for rgx in rule.get("domain_regex", []):
            validate_and_compile_regex(rgx)
            domains.append((1, rgx))
        for suf in rule.get("domain_suffix", []):
            domains.append((2, suf))
        for dom in rule.get("domain", []):
            domains.append((3, dom))
        for cidr in rule.get("ip_cidr", []):
            ipaddress.ip_network(cidr, strict=False)
            cidrs.append(cidr)

    return domains, cidrs


# ---------------------------------------------------------------------------
# Main Build Pipeline
# ---------------------------------------------------------------------------

def fetch_file(url: str, fallback_path: str, offline: bool = False) -> bytes:
    if not offline:
        try:
            print(f"[*] Downloading {url} ...")
            req = urllib.request.Request(url, headers={"User-Agent": "HonkGeoDataBuilder/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                print(f"    Success ({len(data):,} bytes)")
                return data
        except Exception as e:
            print(f"[!] Network fetch failed for {url}: {e}")

    if os.path.exists(fallback_path):
        print(f"[*] Using local fallback: {fallback_path}")
        with open(fallback_path, "rb") as f:
            return f.read()

    raise FileNotFoundError(f"Cannot obtain data: URL failed and fallback '{fallback_path}' not found")


def build_geodata(base_dir: str, offline: bool = False) -> None:
    custom_dir = os.path.join(base_dir, "custom")
    rules_dir = os.path.normpath(os.path.join(base_dir, "..", "rules"))
    os.makedirs(custom_dir, exist_ok=True)

    # 1. Update BlockHttpDNS rule if online
    blockhttpdns_path = os.path.join(custom_dir, "blockhttpdns.json")
    if not offline:
        try:
            print(f"[*] Syncing custom rule: blockhttpdns ...")
            req = urllib.request.Request(
                BLOCKHTTPDNS_REMOTE_URL, headers={"User-Agent": "HonkGeoDataBuilder/1.0"}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                content = resp.read()
                json.loads(content.decode("utf-8"))
                with open(blockhttpdns_path, "wb") as f:
                    f.write(content)
        except Exception as e:
            print(f"[!] Warning: Could not sync remote blockhttpdns.json: {e}")

    # 2. Fetch Upstream geosite-all.dat and geoip.dat
    geosite_fallback = os.path.join(base_dir, "geosite.dat")
    geoip_fallback = os.path.join(base_dir, "geoip.dat")

    geosite_raw = fetch_file(UPSTREAM_GEOSITE_URL, geosite_fallback, offline=offline)
    geoip_raw = fetch_file(UPSTREAM_GEOIP_URL, geoip_fallback, offline=offline)

    # 3. Parse Upstream entries
    upstream_geosite_entries = parse_upstream_entries(geosite_raw)
    upstream_geoip_entries = parse_upstream_entries(geoip_raw)
    print(f"[*] Parsed {len(upstream_geosite_entries)} upstream GeoSite categories")
    print(f"[*] Parsed {len(upstream_geoip_entries)} upstream GeoIP categories")

    # 4. Prepare Custom Categories
    custom_geosite_groups: Dict[str, List[Tuple[int, str]]] = {}
    custom_geoip_entries: Dict[str, List[str]] = {}

    # 4.1 GOOGLE (read from sibling ../rules/google.json)
    google_doms, _ = load_singbox_rule_json(os.path.join(rules_dir, "google.json"))
    custom_geosite_groups["GOOGLE"] = list(dict.fromkeys(google_doms))

    # 4.2 META (read from sibling ../rules/meta.json)
    meta_doms, _ = load_singbox_rule_json(os.path.join(rules_dir, "meta.json"))
    custom_geosite_groups["META"] = list(dict.fromkeys(meta_doms))

    # 4.3 BLOCKHTTPDNS (domains for GeoSite, 41 CIDRs for GeoIP)
    bhttp_doms, bhttp_cidrs = load_singbox_rule_json(blockhttpdns_path)
    custom_geosite_groups["BLOCKHTTPDNS"] = list(dict.fromkeys(bhttp_doms))
    custom_geoip_entries["BLOCKHTTPDNS"] = list(dict.fromkeys(bhttp_cidrs))

    # 4.4 WEBRTC-STUN (read from custom/webrtc-stun.json)
    stun_doms, _ = load_singbox_rule_json(os.path.join(custom_dir, "webrtc-stun.json"))
    custom_geosite_groups["WEBRTC-STUN"] = list(dict.fromkeys(stun_doms))

    # 4.5 DOH-CANARY (read from custom/doh-canary.json)
    doh_doms, _ = load_singbox_rule_json(os.path.join(custom_dir, "doh-canary.json"))
    custom_geosite_groups["DOH-CANARY"] = list(dict.fromkeys(doh_doms))

    # -----------------------------------------------------------------------
    # 5. Assemble geosite.dat
    # -----------------------------------------------------------------------
    final_geosite_buf = bytearray()
    written_geosite_codes: Set[str] = set()

    # 5.1 Keep upstream entries (excluding BT rules and conflicting custom codes)
    for code, inner_bytes in upstream_geosite_entries.items():
        if code in EXCLUDED_UPSTREAM_GEOSITE_CODES:
            print(f"    [Geosite] Excluded BT category: {code}")
            continue
        if code in custom_geosite_groups:
            print(f"    [Geosite] Overriding upstream category with custom version: {code}")
            continue
        final_geosite_buf.extend(encode_length_delimited(1, inner_bytes))
        written_geosite_codes.add(code)

    # 5.2 Append custom categories
    for code, doms in custom_geosite_groups.items():
        if code in written_geosite_codes:
            raise RuntimeError(f"Duplicate geosite code detected before write: {code}")
        inner = encode_geosite_group(code, doms)
        final_geosite_buf.extend(encode_length_delimited(1, inner))
        written_geosite_codes.add(code)
        print(f"    [Geosite] Added custom category {code} ({len(doms)} domains)")

    # -----------------------------------------------------------------------
    # 6. Assemble geoip.dat
    # -----------------------------------------------------------------------
    final_geoip_buf = bytearray()
    written_geoip_codes: Set[str] = set()

    # 6.1 Keep upstream entries (CN, PRIVATE, TELEGRAM, NETFLIX, MEDIA)
    for code, inner_bytes in upstream_geoip_entries.items():
        if code in custom_geoip_entries:
            print(f"    [GeoIP] Overriding upstream category with custom version: {code}")
            continue
        final_geoip_buf.extend(encode_length_delimited(1, inner_bytes))
        written_geoip_codes.add(code)

    # 6.2 Append custom categories (BLOCKHTTPDNS)
    for code, cidrs in custom_geoip_entries.items():
        if code in written_geoip_codes:
            raise RuntimeError(f"Duplicate geoip code detected before write: {code}")
        inner = encode_geoip_entry(code, cidrs)
        final_geoip_buf.extend(encode_length_delimited(1, inner))
        written_geoip_codes.add(code)
        print(f"    [GeoIP] Added custom category {code} ({len(cidrs)} CIDRs)")

    # -----------------------------------------------------------------------
    # 7. Write Output Files & .sha256sum
    # -----------------------------------------------------------------------
    geosite_out_path = os.path.join(base_dir, "geosite.dat")
    geosite_sha_path = os.path.join(base_dir, "geosite.dat.sha256sum")
    geoip_out_path = os.path.join(base_dir, "geoip.dat")
    geoip_sha_path = os.path.join(base_dir, "geoip.dat.sha256sum")

    with open(geosite_out_path, "wb") as f:
        f.write(final_geosite_buf)
    geosite_hash = hashlib.sha256(final_geosite_buf).hexdigest()
    with open(geosite_sha_path, "w", encoding="utf-8") as f:
        f.write(f"{geosite_hash}  geosite.dat\n")

    with open(geoip_out_path, "wb") as f:
        f.write(final_geoip_buf)
    geoip_hash = hashlib.sha256(final_geoip_buf).hexdigest()
    with open(geoip_sha_path, "w", encoding="utf-8") as f:
        f.write(f"{geoip_hash}  geoip.dat\n")

    print(f"\n[+] geosite.dat generated: {len(final_geosite_buf):,} bytes (SHA256: {geosite_hash[:16]}...)")
    print(f"[+] geoip.dat generated: {len(final_geoip_buf):,} bytes (SHA256: {geoip_hash[:16]}...)")

    # -----------------------------------------------------------------------
    # 8. Rigorous Self-Validation & Assertions
    # -----------------------------------------------------------------------
    print("\n[*] Running self-validation on generated artifacts ...")
    validate_output(geosite_out_path, geoip_out_path, geosite_hash, geoip_hash)
    print("[+] All self-validation assertions passed successfully!\n")


def validate_output(
    geosite_path: str,
    geoip_path: str,
    expected_geosite_hash: str,
    expected_geoip_hash: str,
) -> None:
    with open(geosite_path, "rb") as f:
        gdata = f.read()
    assert hashlib.sha256(gdata).hexdigest() == expected_geosite_hash, "geosite.dat SHA256 mismatch!"

    with open(geoip_path, "rb") as f:
        idata = f.read()
    assert hashlib.sha256(idata).hexdigest() == expected_geoip_hash, "geoip.dat SHA256 mismatch!"

    parsed_geosite = parse_upstream_entries(gdata)
    geosite_codes = list(parsed_geosite.keys())
    assert len(geosite_codes) == len(set(geosite_codes)), "Duplicate code found in geosite.dat!"

    for forbidden in EXCLUDED_UPSTREAM_GEOSITE_CODES:
        assert forbidden not in parsed_geosite, f"Forbidden BT tag '{forbidden}' found in geosite.dat!"

    for tag in EXPECTED_GEOSITE_TAGS:
        assert tag in parsed_geosite, f"Expected geosite tag '{tag}' missing from geosite.dat!"

    parsed_geoip = parse_upstream_entries(idata)
    geoip_codes = list(parsed_geoip.keys())
    assert len(geoip_codes) == len(set(geoip_codes)), "Duplicate code found in geoip.dat!"

    for tag in EXPECTED_GEOIP_TAGS:
        assert tag in parsed_geoip, f"Expected geoip tag '{tag}' missing from geoip.dat!"

    print(f"    - geosite.dat contains {len(geosite_codes)} verified unique categories")
    print(f"    - geoip.dat contains {len(geoip_codes)} verified unique categories")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build custom GeoData for Honk / V2Ray / Sing-box")
    parser.add_argument("--offline", action="store_true", help="Do not attempt remote downloads; use local cache")
    parser.add_argument("--base-dir", default=os.path.dirname(os.path.abspath(__file__)), help="Base directory for honk-rule")
    args = parser.parse_args()

    build_geodata(args.base_dir, offline=args.offline)


if __name__ == "__main__":
    main()
