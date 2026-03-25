from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NavItem:
    label: str
    endpoint: str
    icon: str
    group: str | None = None
    view_args: dict[str, Any] | None = None


PRIMARY_NAV: list[NavItem] = [
    NavItem("Overview", "dashboard.index", "layout-dashboard"),
    NavItem("Devices", "devices.index", "server"),
    NavItem("Observe", "observe.index", "radar"),
    NavItem("Ports", "ports.index", "splits"),
    NavItem("Networks", "networks.index", "network"),
    NavItem("Activity", "audit.index", "activity"),
    NavItem("Maintenance", "system.index", "file-text"),
    NavItem("Settings", "settings.index", "settings"),
]

SYSTEM_ACTIONS: list[NavItem] = [
    NavItem("Hilfe", "system.index", "life-buoy"),
    NavItem("Benachrichtigungen", "audit.index", "bell"),
    NavItem("Konto", "auth.users", "user-round"),
]

SETTINGS_NAV: list[NavItem] = [
    NavItem("Site", "settings.section", "", "Core", {"section_slug": "site"}),
    NavItem("Wireless Networks", "settings.section", "", "Core", {"section_slug": "wireless-networks"}),
    NavItem("Networks", "settings.section", "", "Core", {"section_slug": "networks"}),
    NavItem("Routing & Firewall", "settings.section", "", "Core", {"section_slug": "routing-firewall"}),
    NavItem("Threat Management", "settings.section", "", "Core", {"section_slug": "threat-management"}),
    NavItem("DPI", "settings.section", "", "Core", {"section_slug": "dpi"}),
    NavItem("Guest Control", "settings.section", "", "Core", {"section_slug": "guest-control"}),
    NavItem("Profiles", "settings.section", "", "Core", {"section_slug": "profiles"}),
    NavItem("Services", "settings.section", "", "Core", {"section_slug": "services"}),
    NavItem("Admins", "auth.users", "", "Administration"),
    NavItem("User Groups", "settings.section", "", "Administration", {"section_slug": "user-groups"}),
    NavItem("Controller", "settings.section", "", "Controller", {"section_slug": "controller"}),
    NavItem("User Interface", "settings.section", "", "Controller", {"section_slug": "user-interface"}),
    NavItem("Notifications", "settings.section", "", "Controller", {"section_slug": "notifications"}),
    NavItem("Remote Access", "settings.section", "", "Controller", {"section_slug": "remote-access"}),
    NavItem("Maintenance", "settings.section", "", "Controller", {"section_slug": "maintenance"}),
    NavItem("Backup", "settings.section", "", "Controller", {"section_slug": "backup"}),
]

PAGE_TITLES = {
    "dashboard.index": "Overview",
    "devices.index": "Devices",
    "devices.detail": "Device Center",
    "devices.advanced": "Advanced Config",
    "observe.index": "Observe",
    "observe.device": "Observe",
    "ports.index": "Ports",
    "vlans.index": "VLANs",
    "networks.index": "Networks",
    "audit.index": "Activity",
    "system.index": "Maintenance",
    "settings.index": "Settings",
    "settings.section": "Settings",
    "auth.users": "Settings · Admins",
}


def get_primary_active(endpoint: str | None) -> str:
    if not endpoint:
        return "dashboard"
    if endpoint.startswith("settings") or endpoint.startswith("auth.users"):
        return "settings"
    if endpoint.startswith("observe"):
        return "observe"
    return endpoint.split(".")[0]
