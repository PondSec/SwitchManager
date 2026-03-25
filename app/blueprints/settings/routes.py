from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models.models import AppSetting

bp = Blueprint("settings", __name__, url_prefix="/settings")

SETTINGS_SECTIONS = {
    "site": {
        "title": "Site",
        "description": "Globale Standortparameter für den Controller.",
        "fields": [
            {"key": "site_name", "label": "Site Name", "type": "text", "placeholder": "NOC-HQ"},
            {"key": "timezone", "label": "Timezone", "type": "text", "placeholder": "UTC"},
            {"key": "auto_discovery", "label": "Auto Discovery aktiv", "type": "checkbox"},
        ],
    },
    "wireless-networks": {
        "title": "Wireless Networks",
        "description": "WLAN-Policies und SSID-Vorgaben.",
        "fields": [
            {"key": "default_ssid", "label": "Default SSID", "type": "text", "placeholder": "Corp-WLAN"},
            {"key": "wpa_mode", "label": "Security Mode", "type": "text", "placeholder": "WPA2/WPA3"},
            {"key": "radio_optimization", "label": "Radio Optimization", "type": "checkbox"},
        ],
    },
    "networks": {
        "title": "Networks",
        "description": "L3/L2 Netzwerkparameter.",
        "fields": [
            {"key": "management_vlan", "label": "Management VLAN", "type": "text", "placeholder": "10"},
            {"key": "default_gateway", "label": "Default Gateway", "type": "text", "placeholder": "10.0.0.1"},
            {"key": "dhcp_relay", "label": "DHCP Relay", "type": "checkbox"},
        ],
    },
    "routing-firewall": {
        "title": "Routing & Firewall",
        "description": "Routen und Baseline-Firewall-Regeln.",
        "fields": [
            {"key": "policy_mode", "label": "Policy Mode", "type": "text", "placeholder": "Balanced"},
            {"key": "default_route", "label": "Default Route", "type": "text", "placeholder": "wan1"},
            {"key": "ids_fallback_allow", "label": "Fallback allow traffic", "type": "checkbox"},
        ],
    },
    "threat-management": {
        "title": "Threat Management",
        "description": "IDS/IPS Betriebsparameter.",
        "fields": [
            {"key": "ips_mode", "label": "IPS Mode", "type": "text", "placeholder": "Detection"},
            {"key": "signature_level", "label": "Signature Level", "type": "text", "placeholder": "Balanced"},
            {"key": "block_malicious_ips", "label": "Block malicious IPs", "type": "checkbox"},
        ],
    },
    "dpi": {
        "title": "DPI",
        "description": "Application Detection und Traffic-Metadaten.",
        "fields": [
            {"key": "retention_days", "label": "Retention Days", "type": "text", "placeholder": "30"},
            {"key": "sampling_interval", "label": "Sampling (s)", "type": "text", "placeholder": "60"},
            {"key": "dpi_enabled", "label": "DPI aktiv", "type": "checkbox"},
        ],
    },
    "guest-control": {
        "title": "Guest Control",
        "description": "Portal und Gastzugangs-Policies.",
        "fields": [
            {"key": "portal_name", "label": "Portal Name", "type": "text", "placeholder": "Guest Portal"},
            {"key": "session_timeout", "label": "Session Timeout (min)", "type": "text", "placeholder": "120"},
            {"key": "voucher_required", "label": "Voucher erforderlich", "type": "checkbox"},
        ],
    },
    "profiles": {
        "title": "Profiles",
        "description": "Port- und WLAN-Profildefaults.",
        "fields": [
            {"key": "default_port_profile", "label": "Default Port Profile", "type": "text", "placeholder": "All"},
            {"key": "voice_vlan", "label": "Voice VLAN", "type": "text", "placeholder": "20"},
            {"key": "profile_lock", "label": "Profile Lock", "type": "checkbox"},
        ],
    },
    "services": {
        "title": "Services",
        "description": "Integrierte Dienste im Controller.",
        "fields": [
            {"key": "ntp_server", "label": "NTP Server", "type": "text", "placeholder": "pool.ntp.org"},
            {"key": "syslog_target", "label": "Syslog Target", "type": "text", "placeholder": "10.0.0.20"},
            {"key": "snmp_enabled", "label": "SNMP aktiv", "type": "checkbox"},
        ],
    },
    "user-groups": {
        "title": "User Groups",
        "description": "Role Bundles für Operatoren.",
        "fields": [
            {"key": "default_group", "label": "Default Group", "type": "text", "placeholder": "read-only"},
            {"key": "max_sessions", "label": "Max Sessions", "type": "text", "placeholder": "2"},
            {"key": "mfa_required", "label": "MFA verpflichtend", "type": "checkbox"},
        ],
    },
    "controller": {
        "title": "Controller",
        "description": "Controller Runtime und Telemetrie.",
        "fields": [
            {"key": "telemetry_endpoint", "label": "Telemetry Endpoint", "type": "text", "placeholder": "https://telemetry.local"},
            {"key": "session_ttl", "label": "Session TTL (min)", "type": "text", "placeholder": "30"},
            {
                "key": "ssh_host_key_policy",
                "label": "SSH Host-Key Policy",
                "type": "select",
                "options": [
                    {"value": "reject", "label": "reject (sicher)"},
                    {"value": "warning", "label": "warning"},
                    {"value": "auto-add", "label": "auto-add (einfach)"},
                ],
            },
            {"key": "debug_mode", "label": "Debug Mode", "type": "checkbox"},
        ],
    },
    "user-interface": {
        "title": "User Interface",
        "description": "Clientseitiges Bedienverhalten.",
        "fields": [
            {"key": "density", "label": "Density", "type": "text", "placeholder": "compact"},
            {"key": "home_page", "label": "Start Page", "type": "text", "placeholder": "dashboard"},
            {"key": "show_tooltips", "label": "Tooltips anzeigen", "type": "checkbox"},
        ],
    },
    "notifications": {
        "title": "Notifications",
        "description": "Alarmkanäle und Schwellwerte.",
        "fields": [
            {"key": "mail_to", "label": "Alert E-Mail", "type": "text", "placeholder": "noc@example.org"},
            {"key": "critical_threshold", "label": "Critical threshold", "type": "text", "placeholder": "5"},
            {"key": "push_enabled", "label": "Push aktiv", "type": "checkbox"},
        ],
    },
    "remote-access": {
        "title": "Remote Access",
        "description": "Fernzugriff und VPN-Optionen.",
        "fields": [
            {"key": "remote_fqdn", "label": "Remote FQDN", "type": "text", "placeholder": "controller.example.org"},
            {"key": "vpn_profile", "label": "VPN Profile", "type": "text", "placeholder": "noc-vpn"},
            {"key": "remote_enabled", "label": "Remote Access aktiv", "type": "checkbox"},
        ],
    },
    "maintenance": {
        "title": "Maintenance",
        "description": "Wartungsfenster und Cleanup.",
        "fields": [
            {"key": "window", "label": "Maintenance Window", "type": "text", "placeholder": "Sun 02:00-04:00"},
            {"key": "log_retention", "label": "Log Retention (days)", "type": "text", "placeholder": "90"},
            {"key": "auto_cleanup", "label": "Auto Cleanup", "type": "checkbox"},
        ],
    },
    "backup": {
        "title": "Backup",
        "description": "Controller-Backups und Rotationen.",
        "fields": [
            {"key": "backup_target", "label": "Backup Target", "type": "text", "placeholder": "s3://switchmanager"},
            {"key": "backup_schedule", "label": "Schedule", "type": "text", "placeholder": "Daily 03:00"},
            {"key": "encryption_enabled", "label": "Backup Encryption", "type": "checkbox"},
        ],
    },
}


@bp.route("/")
@login_required
def index():
    return redirect(url_for("settings.section", section_slug="site"))


@bp.route("/<string:section_slug>", methods=["GET", "POST"])
@login_required
def section(section_slug: str):
    section_meta = SETTINGS_SECTIONS.get(section_slug)
    if not section_meta:
        flash("Unbekannte Settings-Kategorie.", "error")
        return redirect(url_for("settings.index"))

    settings_map = _load_section_values(section_slug)

    if section_slug == "controller":
        settings_map.setdefault("ssh_host_key_policy", "reject")

    if request.method == "POST":
        for field in section_meta["fields"]:
            if field["type"] == "checkbox":
                settings_map[field["key"]] = "1" if request.form.get(field["key"]) == "on" else "0"
            else:
                settings_map[field["key"]] = (request.form.get(field["key"]) or "").strip()
        _save_section_values(section_slug, settings_map)
        flash(f"{section_meta['title']} gespeichert.", "success")
        return redirect(url_for("settings.section", section_slug=section_slug))

    return render_template(
        "settings/section.html",
        section_slug=section_slug,
        section_meta=section_meta,
        settings_map=settings_map,
    )


def _load_section_values(section_slug: str) -> dict[str, str]:
    rows = AppSetting.query.filter_by(section=section_slug).all()
    return {row.key: row.value for row in rows}


def _save_section_values(section_slug: str, data: dict[str, str]) -> None:
    existing_rows = {row.key: row for row in AppSetting.query.filter_by(section=section_slug).all()}
    for key, value in data.items():
        row = existing_rows.get(key)
        if row:
            row.value = value
        else:
            db.session.add(AppSetting(section=section_slug, key=key, value=value))
    db.session.commit()
