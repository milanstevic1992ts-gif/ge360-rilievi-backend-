from __future__ import annotations

import ipaddress
import json
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from typing import Callable

from .config import BridgeSettings

Runner = Callable[[list[str], str | None, float], tuple[int, str, str]]


def run_command(args: list[str], input_text: str | None = None, timeout: float = 4.0) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            args, input=input_text, capture_output=True, text=True, check=False, timeout=timeout
        )
        return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)


def classify_external_ipv4(value: str | None) -> str:
    if not value:
        return "UNKNOWN"
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return "UNKNOWN"
    if not isinstance(ip, ipaddress.IPv4Address):
        return "UNKNOWN"
    if ip in ipaddress.ip_network("100.64.0.0/10"):
        return "CGNAT"
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
        return "NON_PUBLIC"
    return "PUBLIC"


def upnp_external_ipv4(runner: Runner = run_command) -> tuple[str | None, str | None]:
    exe = shutil.which("upnpc")
    if not exe:
        return None, "upnpc not installed"
    code, out, err = runner([exe, "-s"], None, 5.0)
    if code != 0:
        return None, err or f"upnpc exited with {code}"
    match = re.search(r"ExternalIPAddress\s*=\s*([0-9.]+)", out)
    return (match.group(1), None) if match else (None, "router did not report ExternalIPAddress")


def default_route(runner: Runner = run_command) -> dict:
    exe = shutil.which("ip") or "ip"
    code, out, err = runner([exe, "route", "show", "default"], None, 2.0)
    if code != 0:
        return {"gateway": None, "interface": None, "error": err or f"ip exited with {code}"}
    line = out.splitlines()[0] if out else ""
    gateway = re.search(r"\bvia\s+(\S+)", line)
    interface = re.search(r"\bdev\s+(\S+)", line)
    return {
        "gateway": gateway.group(1) if gateway else None,
        "interface": interface.group(1) if interface else None,
        "error": None,
    }


def local_ipv4_for_default_route(runner: Runner = run_command) -> str | None:
    exe = shutil.which("ip") or "ip"
    code, out, _ = runner([exe, "route", "get", "1.1.1.1"], None, 2.0)
    if code != 0:
        return None
    match = re.search(r"\bsrc\s+([0-9.]+)", out)
    return match.group(1) if match else None


def global_ipv6_addresses(runner: Runner = run_command) -> list[str]:
    exe = shutil.which("ip") or "ip"
    code, out, _ = runner([exe, "-j", "-6", "addr", "show", "scope", "global"], None, 2.5)
    if code != 0 or not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    found: list[str] = []
    for iface in data if isinstance(data, list) else []:
        for info in iface.get("addr_info", []) if isinstance(iface, dict) else []:
            value = info.get("local")
            if not value:
                continue
            try:
                ip = ipaddress.ip_address(value)
            except ValueError:
                continue
            if isinstance(ip, ipaddress.IPv6Address) and ip.is_global:
                found.append(str(ip))
    return found


def port_mapping_capabilities() -> dict:
    return {
        "upnp_igd": bool(shutil.which("upnpc")),
        "nat_pmp": bool(shutil.which("natpmpc")),
        "pcp": bool(shutil.which("pcp") or shutil.which("pcp-client")),
    }


def format_endpoint(host: str, port: int) -> str:
    clean = host.strip().strip("[]")
    try:
        ip = ipaddress.ip_address(clean)
    except ValueError:
        return f"{clean}:{port}"
    return f"[{ip}]:{port}" if isinstance(ip, ipaddress.IPv6Address) else f"{ip}:{port}"


@dataclass(frozen=True)
class PublicEndpoint:
    available: bool
    endpoint: str | None
    host: str | None
    source: str
    state_code: str
    message: str | None = None
    externally_verified: bool = False


def resolve_public_endpoint(settings: BridgeSettings, runner: Runner = run_command) -> PublicEndpoint:
    if settings.public_host:
        host = settings.public_host.strip().strip("[]")
        # An explicitly configured global IPv6 endpoint is valid even when the
        # router's IPv4 WAN is behind CGNAT. IPv4 CGNAT must not disable IPv6.
        try:
            configured_ip = ipaddress.ip_address(host)
        except ValueError:
            configured_ip = None

        if isinstance(configured_ip, ipaddress.IPv6Address):
            if configured_ip.is_global:
                return PublicEndpoint(
                    True,
                    format_endpoint(host, settings.listen_port),
                    host,
                    "configured-ipv6",
                    "ENDPOINT_CONFIGURED_IPV6",
                )
            return PublicEndpoint(
                False, None, host, "configured-ipv6", "PUBLIC_ENDPOINT_REQUIRED",
                "L'IPv6 configurato non è un indirizzo globale raggiungibile.",
            )

        classification = classify_external_ipv4(host)
        router_external_ip, _ = upnp_external_ipv4(runner)
        router_classification = classify_external_ipv4(router_external_ip)
        if classification in {"CGNAT", "NON_PUBLIC"} or router_classification in {"CGNAT", "NON_PUBLIC"}:
            return PublicEndpoint(
                False, None, router_external_ip or host, "configured", "REMOTE_ACCESS_UNAVAILABLE_CGNAT",
                "La rete IPv4 non consente connessioni dirette in ingresso. Usa un IPv6 globale raggiungibile o un relay esterno.",
            )
        return PublicEndpoint(True, format_endpoint(host, settings.listen_port), host, "configured", "ENDPOINT_CONFIGURED")

    external_ip, _ = upnp_external_ipv4(runner)
    classification = classify_external_ipv4(external_ip)
    if classification in {"CGNAT", "NON_PUBLIC"}:
        return PublicEndpoint(
            False, None, external_ip, "upnp", "REMOTE_ACCESS_UNAVAILABLE_CGNAT",
            "La rete non consente connessioni dirette in ingresso. È necessario un IP pubblico, IPv6 raggiungibile o un relay esterno.",
        )
    if classification == "PUBLIC" and external_ip:
        return PublicEndpoint(True, format_endpoint(external_ip, settings.listen_port), external_ip, "upnp", "PUBLIC_IPV4_DETECTED")

    ipv6 = global_ipv6_addresses(runner)
    if ipv6:
        return PublicEndpoint(True, format_endpoint(ipv6[0], settings.listen_port), ipv6[0], "ipv6", "PUBLIC_IPV6_DETECTED")

    return PublicEndpoint(
        False, None, None, "unknown", "PUBLIC_ENDPOINT_REQUIRED",
        "Imposta GE360_PUBLIC_HOST oppure configura un IP pubblico/IPv6 raggiungibile.",
    )


def try_upnp_mapping(settings: BridgeSettings, runner: Runner = run_command) -> dict:
    if not settings.auto_port_mapping:
        return {"enabled": False, "attempted": False, "mapped": False, "error": None}
    exe = shutil.which("upnpc")
    local_ip = local_ipv4_for_default_route(runner)
    if not exe or not local_ip:
        return {"enabled": True, "attempted": False, "mapped": False, "error": "UPnP mapping unavailable: upnpc or LAN IPv4 missing"}
    args = [exe, "-e", "GE360 DIRECT BRIDGE", "-a", local_ip, str(settings.listen_port), str(settings.listen_port), "UDP"]
    code, out, err = runner(args, None, 8.0)
    mapped = code == 0 and ("is redirected" in out.lower() or "external" in out.lower() or "addportmapping" in out.lower())
    return {"enabled": True, "attempted": True, "mapped": mapped, "error": None if mapped else (err or out[-300:])}


def backend_port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False
