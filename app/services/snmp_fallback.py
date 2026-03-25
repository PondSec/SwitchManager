from __future__ import annotations

import re
import shutil
import subprocess


def _run_snmpwalk(host: str, community: str, oid: str, timeout: int) -> str:
    snmpwalk = shutil.which("snmpwalk")
    if not snmpwalk:
        return ""
    cmd = [snmpwalk, "-v2c", "-c", community, "-t", str(timeout), "-r", "1", host, oid]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=max(2, timeout + 1), check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout or ""


def _candidate_communities(community: str | None) -> list[str]:
    candidates = [community or "", "public", "private"]
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            continue
        ordered.append(normalized)
        seen.add(normalized)
    return ordered


def probe_interface_states(host: str, community: str | None = None, timeout: int = 2) -> list[dict]:
    """Best-effort SNMP fallback for ifOperStatus/ifName."""
    chosen_community = None
    raw_status = ""
    for candidate in _candidate_communities(community):
        raw_status = _run_snmpwalk(host, candidate, "IF-MIB::ifOperStatus", timeout)
        if raw_status:
            chosen_community = candidate
            break
    if not raw_status:
        return []

    index_to_name: dict[int, str] = {}
    raw_names = _run_snmpwalk(host, chosen_community or "public", "IF-MIB::ifName", timeout)
    for line in raw_names.splitlines():
        match = re.search(r"ifName\.(\d+)\s*=\s*STRING:\s*(.+)$", line)
        if not match:
            continue
        index_to_name[int(match.group(1))] = match.group(2).strip().strip('"')

    rows: list[dict] = []
    for line in raw_status.splitlines():
        match = re.search(r"ifOperStatus\.(\d+)\s*=\s*INTEGER:\s*([a-zA-Z]+)", line)
        if not match:
            continue

        if_index = int(match.group(1))
        status = match.group(2).lower()
        iface_name = index_to_name.get(if_index, str(if_index)).lower()

        if iface_name.startswith("eth"):
            try:
                port_number = int(iface_name.removeprefix("eth")) + 1
            except ValueError:
                port_number = if_index
        else:
            digit_match = re.search(r"(\d+)", iface_name)
            port_number = int(digit_match.group(1)) if digit_match else if_index

        rows.append(
            {
                "port_number": port_number,
                "link_state": "up" if status == "up" else "down",
                "admin_enabled": True,
            }
        )

    return rows
