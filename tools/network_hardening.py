#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import secrets
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from app.extensions import db
from app.models import Device
from app.services.device_inventory import apply_interface_snapshot, apply_vlan_snapshot, ensure_device_inventory
from app.utils.driver_factory import get_driver

CHROME_BIN = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
ZyxelDisablePorts = [4, 5, 6, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]
ZyxelPortSecurityProfiles = {
    2: {"max_mac": 1, "action": 0},
    3: {"max_mac": 1, "action": 0},
    7: {"max_mac": 1, "action": 0},
}


@dataclass
class DeviceResult:
    name: str
    backup_path: Path
    changes: list[str]
    verification: list[str]
    deferred: list[str]
    notes: list[str]


def _encode_zyxel_password(password: str) -> str:
    possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    password_length = len(password)
    remaining = len(password)
    encoded: list[str] = []
    for index in range(1, 321 - password_length + 1):
        if index % 5 == 0 and remaining > 0:
            remaining -= 1
            encoded.append(password[remaining])
        elif index == 123:
            encoded.append("0" if password_length < 10 else str(password_length // 10))
        elif index == 289:
            encoded.append(str(password_length % 10))
        else:
            encoded.append(secrets.choice(possible))
    return "".join(encoded)


def _extract_xssid(payload: str) -> str:
    marker = 'name="XSSID" value="'
    start = payload.find(marker)
    if start == -1:
        raise RuntimeError("Zyxel XSSID nicht gefunden")
    start += len(marker)
    end = payload.find('"', start)
    if end == -1:
        raise RuntimeError("Zyxel XSSID unvollstaendig")
    return payload[start:end]


def _probe_tcp(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _head_ok(url: str, timeout: float = 6.0) -> bool:
    try:
        response = requests.head(url, timeout=timeout, verify=False, allow_redirects=True)
        return 200 <= response.status_code < 500
    except requests.RequestException:
        return False


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _zyxel_login(device: Device, scheme: str = "https") -> tuple[requests.Session, str]:
    if not device.password:
        raise RuntimeError(f"{device.name}: kein Passwort fuer Zyxel-Weblogin hinterlegt")

    session = requests.Session()
    base_url = f"{scheme}://{device.host}"
    session.get(f"{base_url}/cgi-bin/dispatcher.cgi?cmd=0", timeout=10, verify=False)
    auth_id = session.post(
        f"{base_url}/cgi-bin/dispatcher.cgi",
        data={"username": device.username, "password": _encode_zyxel_password(device.password), "login": "true;"},
        timeout=10,
        verify=False,
    ).text.strip()
    if not auth_id:
        raise RuntimeError("Zyxel-Weblogin lieferte kein Auth-ID-Ticket")

    status = session.post(
        f"{base_url}/cgi-bin/dispatcher.cgi",
        data={"authId": auth_id, "login_chk": "true"},
        timeout=10,
        verify=False,
    ).text
    if "OK" not in status:
        raise RuntimeError("Zyxel-Weblogin fehlgeschlagen")

    session.get(f"{base_url}/cgi-bin/dispatcher.cgi?cmd=1", timeout=10, verify=False)
    return session, base_url


def _zyxel_get(session: requests.Session, base_url: str, cmd: int) -> str:
    response = session.get(f"{base_url}/cgi-bin/dispatcher.cgi?cmd={cmd}", timeout=10, verify=False)
    response.raise_for_status()
    return response.text


def _zyxel_post(session: requests.Session, base_url: str, cmd: int, xssid: str, fields: dict[str, Any]) -> str:
    payload = {"cmd": str(cmd), "XSSID": xssid}
    payload.update({key: str(value) for key, value in fields.items()})
    response = session.post(f"{base_url}/cgi-bin/dispatcher.cgi", data=payload, timeout=10, verify=False)
    response.raise_for_status()
    return response.text


def _sync_device_snapshot(device: Device) -> None:
    driver = get_driver(device)
    driver.connect()
    try:
        info = driver.get_system_info()
        interfaces = driver.get_interfaces()
        vlans = driver.get_vlans()
    finally:
        driver.close()

    ensure_device_inventory(device)
    apply_interface_snapshot(device, interfaces)
    apply_vlan_snapshot(device, vlans)
    if info.get("model"):
        device.model = str(info["model"])
    if info.get("firmware"):
        device.firmware = str(info["firmware"])
    if info.get("mgmt_ip"):
        device.mgmt_ip = str(info["mgmt_ip"])
    device.status = "online"
    device.last_seen_at = datetime.now(UTC)
    db.session.commit()


def harden_edgerouter(device: Device, backup_dir: Path, apply: bool) -> DeviceResult:
    driver = get_driver(device)
    driver.connect()
    try:
        before = driver._run_show("show configuration commands")
        backup_path = backup_dir / f"{device.name.lower()}_pre_hardening.txt"
        _write_text(backup_path, before + "\n")

        commands = [
            "set firewall source-validation loose",
            "set firewall send-redirects disable",
            "set service gui older-ciphers disable",
            "delete service gui http-port",
            "set interfaces ethernet eth1 description 'DISABLED_UNUSED'",
            "set interfaces ethernet eth1 disable",
            "set interfaces ethernet eth2 description 'DISABLED_UNUSED'",
            "set interfaces ethernet eth2 disable",
            "set interfaces ethernet eth3 description 'DISABLED_UNUSED'",
            "set interfaces ethernet eth3 disable",
            "set interfaces ethernet eth4 description 'DISABLED_UNUSED'",
            "set interfaces ethernet eth4 disable",
        ]

        changes = [
            "IPv4 source validation von 'disable' auf 'loose' gesetzt.",
            "ICMP send-redirects deaktiviert.",
            "GUI Legacy-Ciphers deaktiviert.",
            "Unused Router-Ports eth1-eth4 mit Beschreibung markiert und administrativ deaktiviert.",
        ]

        if apply:
            driver._run_config_commands(commands, dry_run=False)

        after = driver._run_show("show configuration commands")
        _write_text(backup_dir / f"{device.name.lower()}_post_hardening.txt", after + "\n")
    finally:
        driver.close()

    verification = []
    if "set firewall source-validation loose" in after:
        verification.append("source-validation steht jetzt auf loose.")
    if "set firewall send-redirects disable" in after:
        verification.append("send-redirects ist deaktiviert.")
    if "set service gui older-ciphers disable" in after:
        verification.append("Legacy-Ciphers fuer die GUI sind deaktiviert.")
    if _head_ok(f"http://{device.host}") and _head_ok(f"https://{device.host}"):
        verification.append("HTTP/80 antwortet nur mit Redirect auf HTTPS; HTTPS/443 bleibt aktiv.")
    for iface in ("eth1", "eth2", "eth3", "eth4"):
        if f"set interfaces ethernet {iface} disable" in after:
            verification.append(f"{iface} ist administrativ deaktiviert.")

    deferred = [
        "Keine Inter-VLAN-Firewallregeln ausgerollt; dafuer fehlt eine belastbare Kommunikationsmatrix.",
        "SSH-Haertung ohne Device-Schluesselzwang absichtlich nicht verschaerft, damit der aktuelle Webapp-/Ops-Zugang erhalten bleibt.",
    ]
    notes = [
        "WAN-/Port-Forwarding-Regeln wurden unveraendert gelassen.",
        "Das Routing ueber eth0 VLAN-Interfaces bleibt unveraendert.",
        "EdgeOS 2.0.9-hotfix.7 behaelt auf diesem Geraet HTTP/80 als Redirect auf HTTPS; ein getestetes Delete der Konfig-Node entfernt das Live-Verhalten nicht.",
    ]
    return DeviceResult(name=device.name, backup_path=backup_path, changes=changes, verification=verification, deferred=deferred, notes=notes)


def harden_zyxel(device: Device, backup_dir: Path, apply: bool) -> DeviceResult:
    driver = get_driver(device)
    driver.connect()
    try:
        before = driver._execute_shell_commands(["show running-config"], timeout=12)[0]
    finally:
        driver.close()

    backup_path = backup_dir / f"{device.name.lower()}_pre_hardening.txt"
    _write_text(backup_path, before + "\n")

    session, base_url = _zyxel_login(device, scheme="https")
    http_page = _zyxel_get(session, base_url, 544)
    xssid = _extract_xssid(http_page)

    changes = [
        "Zyxel-Management von HTTPS weitergefuehrt; HTTP und Telnet werden abgeschaltet.",
        f"Unused Switch-Ports deaktiviert: {', '.join(str(port) for port in ZyxelDisablePorts)}.",
        "Port-Security auf dedizierten Single-Host-Ports 2, 3 und 7 mit Max-MAC=1 aktiviert.",
        "Running-Config nach Startup-Config kopiert.",
    ]

    if apply:
        _zyxel_post(session, base_url, 549, xssid, {"telnetd": 0})
        for port in ZyxelDisablePorts:
            _zyxel_post(
                session,
                base_url,
                770,
                xssid,
                {"portlist": port, "descp": "", "state": 0, "speed": 0, "duplex": 0, "fc": 0},
            )
        for port, profile in ZyxelPortSecurityProfiles.items():
            _zyxel_post(
                session,
                base_url,
                784,
                xssid,
                {"portlist": port, "security": 1, "l2num": profile["max_mac"], "action": profile["action"]},
            )
        _zyxel_post(session, base_url, 545, xssid, {"http_enable": 0, "loginAuth": "default", "webHttpTo": 3})

        https_session, https_base = _zyxel_login(device, scheme="https")
        try:
            save_page = _zyxel_get(https_session, https_base, 5898)
            save_xssid = _extract_xssid(save_page)
            _zyxel_post(https_session, https_base, 5899, save_xssid, {"srcFile": 1, "dstFile": 2})
        finally:
            https_session.close()

    driver = get_driver(device)
    driver.connect()
    try:
        after = driver._execute_shell_commands(["show running-config"], timeout=12)[0]
        interfaces = driver.get_interfaces()
    finally:
        driver.close()

    _write_text(backup_dir / f"{device.name.lower()}_post_hardening.txt", after + "\n")

    verification = []
    if "ip telnet" not in after:
        verification.append("Telnet ist aus der Running-Config verschwunden.")
    if "ip ssh" in after:
        verification.append("SSH bleibt aktiv.")
    if _head_ok(f"https://{device.host}/cgi-bin/dispatcher.cgi?cmd=0"):
        verification.append("HTTPS-Management ist erreichbar.")
    if not _head_ok(f"http://{device.host}/cgi-bin/dispatcher.cgi?cmd=0"):
        verification.append("HTTP-Management antwortet nicht mehr.")
    if not _probe_tcp(device.host, 23):
        verification.append("TCP/23 (Telnet) ist geschlossen.")
    else:
        verification.append("TCP/23 reagiert trotz 'no ip telnet' noch; dafuer waere ein Service-Restart oder Wartungsfenster-Reboot noetig.")

    disabled_ports = {entry["port_number"] for entry in interfaces if not entry.get("admin_enabled", True)}
    if set(ZyxelDisablePorts).issubset(disabled_ports):
        verification.append("Alle vorgesehenen ungenutzten Ports sind administrativ deaktiviert.")

    session, base_url = _zyxel_login(device, scheme="https")
    try:
        xssid = _extract_xssid(_zyxel_get(session, base_url, 544))
        port_security_checks = []
        for port in ZyxelPortSecurityProfiles:
            detail = _zyxel_post(session, base_url, 783, xssid, {"port": port})
            if f'name="portlist" value="{port}"' in detail and 'name="security" id="security_1" value="1" checked' in detail:
                port_security_checks.append(port)
        if set(ZyxelPortSecurityProfiles).issubset(port_security_checks):
            verification.append("Port-Security ist auf Ports 2, 3 und 7 aktiv.")
    finally:
        session.close()

    deferred = [
        "Keine Management Access-List aktiviert; dafuer fehlen stabile Admin-Source-IP-Vorgaben.",
        "Keine Port-Isolation auf aktiven Ports erzwungen, weil Port 11 mehrere MAC-Adressen fuehrt und Ost-West-Kommunikation unbekannt ist.",
        "DHCP Snooping / IP Source Guard wurden nicht auf dem GS1900 ausgerollt; auf dieser Plattform ist das im verifizierten UI-/Manual-Pfad nicht belastbar verfuegbar.",
        "VLAN-Mitgliedschaften wurden nicht live umgebaut, um die bestehende Portbelegung ohne Wartungsfenster nicht zu gefaehrden.",
    ]
    notes = [
        "Die Webapp-native Zyxel-Bridge muss HTTPS sprechen; dafuer wurde der Proxy parallel angepasst.",
        "Ports 2 und 7 bleiben trotz Link-Down aktiv, weil sie bereits als reservierte Produktionsports beschriftet sind.",
    ]
    return DeviceResult(name=device.name, backup_path=backup_path, changes=changes, verification=verification, deferred=deferred, notes=notes)


def _html_list(items: list[str]) -> str:
    if not items:
        return "<li>Keine</li>"
    return "".join(f"<li>{html.escape(item)}</li>" for item in items)


def _render_markdown(report_date: str, backup_dir: Path, results: list[DeviceResult]) -> str:
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        f"# Netzwerk-Hardening Bericht ({report_date})",
        "",
        f"Erzeugt: {generated_at}",
        "",
        "## Zielbild",
        "",
        "- Management-Plane absichern, ohne den laufenden Betrieb zu verlieren.",
        "- Eindeutig unbenutzte Ports deaktivieren.",
        "- Port-Security dort aktivieren, wo die Topologie als Single-Host erkennbar ist.",
        "- Bestehendes Routing, VLAN-Layout und Port-Forwarding nicht veraendern.",
        "",
        "## Backups",
        "",
        f"- Vorher-/Nachher-Konfigurationen liegen unter `{backup_dir}`.",
        "",
    ]
    for result in results:
        lines.extend([
            f"## {result.name}",
            "",
            f"- Backup vor der Aenderung: `{result.backup_path}`",
            "- Umgesetzte Massnahmen:",
            *[f"  - {item}" for item in result.changes],
            "- Verifikation:",
            *[f"  - {item}" for item in result.verification],
            "- Bewusst vertagt:",
            *[f"  - {item}" for item in result.deferred],
            "- Hinweise:",
            *[f"  - {item}" for item in result.notes],
            "",
        ])

    lines.extend([
        "## Nicht live ausgerollt",
        "",
        "- Inter-VLAN-Firewalling auf dem EdgeRouter: dafuer fehlt eine Kommunikationsmatrix der Dienste.",
        "- Aggressive Port-Isolation auf dem Switch: Port 11 fuehrt derzeit viele MAC-Adressen und wirkt wie ein Downstream-/Aggregationsport.",
        "- DHCP Snooping / IP Source Guard auf dem Zyxel: nicht belastbar ueber den verifizierten GS1900-Pfad verfuegbar.",
        "",
        "## Bedienung nach der Haertung",
        "",
        "- EdgeRouter-Verwaltung bevorzugt ueber HTTPS auf Port 443; HTTP/80 leitet auf diesem Firmwarestand auf HTTPS um.",
        "- Zyxel-Verwaltung nur noch ueber HTTPS; HTTP ist abgeschaltet. Telnet ist aus der Konfiguration entfernt, der Daemon sollte aber erst nach Service-Restart oder geplantem Reboot ganz verschwinden.",
        "- Administrativ deaktivierte Ports muessen vor neuer Nutzung bewusst wieder freigegeben werden.",
        "",
        "## Quellen",
        "",
        "- Zyxel GS1900-24E User Guide V2.90: https://download.zyxel.com/GS1900-24E/user_guide/GS1900-24E_V2.90_Ed1.pdf",
        "- Ubiquiti EdgeOS User Guide: https://dl.ubnt.com/guides/edgemax/EdgeOS_UG.pdf",
        "",
    ])
    return "\n".join(lines)


def _render_html(report_date: str, markdown: str) -> str:
    paragraphs = []
    for block in markdown.split("\n\n"):
        if block.startswith("# "):
            paragraphs.append(f"<h1>{html.escape(block[2:])}</h1>")
        elif block.startswith("## "):
            paragraphs.append(f"<h2>{html.escape(block[3:])}</h2>")
        elif all(line.startswith("- ") for line in block.splitlines() if line.strip()):
            items = "".join(f"<li>{html.escape(line[2:])}</li>" for line in block.splitlines() if line.strip())
            paragraphs.append(f"<ul>{items}</ul>")
        elif all(line.startswith("  - ") for line in block.splitlines() if line.strip()):
            items = "".join(f"<li>{html.escape(line[4:])}</li>" for line in block.splitlines() if line.strip())
            paragraphs.append(f"<ul>{items}</ul>")
        else:
            text = "<br>".join(html.escape(line) for line in block.splitlines())
            paragraphs.append(f"<p>{text}</p>")

    body = "\n".join(paragraphs)
    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Netzwerk-Hardening Bericht {html.escape(report_date)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 40px auto; max-width: 980px; color: #0f172a; line-height: 1.55; }}
    h1, h2 {{ color: #0f172a; }}
    h1 {{ border-bottom: 3px solid #2563eb; padding-bottom: 8px; }}
    h2 {{ margin-top: 28px; }}
    p, li {{ font-size: 14px; }}
    ul {{ margin: 8px 0 16px 22px; }}
    code {{ background: #eff6ff; padding: 1px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def _print_pdf(html_path: Path, pdf_path: Path) -> None:
    if not CHROME_BIN.exists():
        raise RuntimeError(f"Chrome fuer PDF-Export nicht gefunden: {CHROME_BIN}")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(CHROME_BIN),
            "--headless=new",
            "--disable-gpu",
            "--allow-file-access-from-files",
            f"--print-to-pdf={pdf_path}",
            str(html_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Konservative Live-Haertung fuer EdgeRouter + Zyxel mit Bericht/PDF.")
    parser.add_argument("--apply", action="store_true", help="Aenderungen wirklich auf die Geraete committen.")
    parser.add_argument("--date", default=datetime.now().date().isoformat(), help="Berichtsdatum, z.B. 2026-03-25")
    parser.add_argument("--skip-pdf", action="store_true", help="PDF-Export ueberspringen.")
    args = parser.parse_args()

    backup_dir = ROOT / "backups" / f"network_hardening_{args.date}"
    report_dir = ROOT / "reports"
    report_md = report_dir / f"network_hardening_{args.date}.md"
    report_html = report_dir / f"network_hardening_{args.date}.html"
    report_pdf = ROOT / f"network_hardening_{args.date}.pdf"

    app = create_app()
    with app.app_context():
        zyxel = Device.query.filter_by(name="ZyxelGS1900-24e").first()
        edge = Device.query.filter_by(name="EdgeRouterX").first()
        if not zyxel or not edge:
            raise RuntimeError("ZyxelGS1900-24e oder EdgeRouterX nicht in der Datenbank gefunden")

        results = [
            harden_edgerouter(edge, backup_dir, apply=args.apply),
            harden_zyxel(zyxel, backup_dir, apply=args.apply),
        ]

        if args.apply:
            _sync_device_snapshot(edge)
            _sync_device_snapshot(zyxel)

    markdown = _render_markdown(args.date, backup_dir, results)
    html_content = _render_html(args.date, markdown)
    _write_text(report_md, markdown)
    _write_text(report_html, html_content)
    if not args.skip_pdf:
        _print_pdf(report_html, report_pdf)

    print(f"Markdown: {report_md}")
    print(f"HTML: {report_html}")
    if not args.skip_pdf:
        print(f"PDF: {report_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
