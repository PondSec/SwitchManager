from datetime import datetime

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import csrf, db
from app.forms.device_forms import DeviceForm
from app.models.models import AppSetting, AuditLog, Device, NetworkProfile, Port, VLAN
from app.services.audit_service import write_audit
from app.services.config_workspace import build_config_sections, get_capability_catalog
from app.services.device_center import load_device_center_snapshot
from app.services.device_inventory import apply_interface_snapshot, apply_vlan_snapshot, ensure_device_inventory
from app.services.snmp_fallback import probe_interface_states
from app.services.zyxel_web_config import PORT_DUPLEX_LABELS, PORT_SPEED_LABELS, ZyxelWebConfigClient
from app.services.zyxel_native_proxy import proxy_zyxel_request
from app.utils.device_context import set_selected_device
from app.utils.driver_factory import get_driver

bp = Blueprint("devices", __name__, url_prefix="/devices")


def _extract_value(raw: str, keys: list[str]) -> str | None:
    for line in raw.splitlines():
        normalized = line.strip()
        lower = normalized.lower()
        for key in keys:
            if key in lower and ":" in normalized:
                return normalized.split(":", 1)[1].strip()
    return None


def _parse_vlan_csv(raw: str | None) -> list[int]:
    values: list[int] = []
    seen: set[int] = set()
    for token in (raw or "").replace(";", ",").split(","):
        stripped = token.strip()
        if not stripped:
            continue
        if not stripped.isdigit():
            raise RuntimeError(f"Ungueltige VLAN-ID in Tagged VLANs: {stripped}")
        vlan_id = int(stripped)
        if vlan_id < 1 or vlan_id > 4094:
            raise RuntimeError(f"Tagged VLAN-ID ausserhalb des gueltigen Bereichs: {vlan_id}")
        if vlan_id in seen:
            continue
        seen.add(vlan_id)
        values.append(vlan_id)
    return values


def _parse_zyxel_choice(raw: str | None, allowed: set[str], *, field: str, default: str) -> str:
    value = (raw or default).strip()
    if value not in allowed:
        raise RuntimeError(f"Ungueltige Auswahl fuer {field}: {value}")
    return value


def _derive_zyxel_inventory(memberships: dict[int, str], pvid: int) -> tuple[int, str]:
    untagged_vlans = sorted(vlan_id for vlan_id, code in memberships.items() if code == "3")
    tagged_vlans = sorted(vlan_id for vlan_id, code in memberships.items() if code == "2")

    if untagged_vlans:
        return untagged_vlans[0], "untagged"
    if tagged_vlans:
        return (pvid if pvid > 0 else tagged_vlans[0]), "tagged"
    return max(pvid, 1), "excluded"


def _parse_zyxel_port_members(text: str | None) -> set[int]:
    members: set[int] = set()
    for token in (text or "").replace(";", ",").split(","):
        raw = token.strip()
        if not raw or raw.lower().startswith("lag"):
            continue
        if "-" in raw:
            start_raw, end_raw = raw.split("-", 1)
            if start_raw.strip().isdigit() and end_raw.strip().isdigit():
                start = int(start_raw.strip())
                end = int(end_raw.strip())
                for value in range(min(start, end), max(start, end) + 1):
                    members.add(value)
            continue
        if raw.isdigit():
            members.add(int(raw))
    return members


def _read_zyxel_memberships(device: Device, port_number: int) -> dict[int, str]:
    driver = get_driver(device)
    try:
        driver.connect()
        live_vlans = driver.get_vlans()
    finally:
        driver.close()

    memberships: dict[int, str] = {}
    for vlan in live_vlans:
        vlan_id = vlan.get("vlan_id")
        if vlan_id is None:
            continue
        if port_number in _parse_zyxel_port_members(vlan.get("untagged_ports")):
            memberships[int(vlan_id)] = "3"
        elif port_number in _parse_zyxel_port_members(vlan.get("tagged_ports")):
            memberships[int(vlan_id)] = "2"
        else:
            memberships[int(vlan_id)] = "0"
    return memberships


def _apply_zyxel_port_changes(device: Device, port: Port) -> tuple[dict, int, str]:
    client = ZyxelWebConfigClient(device.host, device.username, device.password or "")
    alias = request.form.get("alias", port.alias or "")
    admin_enabled = request.form.get("admin_enabled") == "on"
    speed_code = _parse_zyxel_choice(
        request.form.get("speed"),
        {"0", "1", "2", "3"},
        field="Port Speed",
        default=(request.form.get("current_speed") or "0"),
    )
    duplex_code = _parse_zyxel_choice(
        request.form.get("duplex"),
        {"0", "1", "2"},
        field="Port Duplex",
        default=(request.form.get("current_duplex") or "0"),
    )
    frame_type_code = _parse_zyxel_choice(
        request.form.get("frame_type"),
        {"0", "1", "2"},
        field="Accepted Frame Type",
        default=(request.form.get("current_frame_type") or "0"),
    )
    flow_control_enabled = request.form.get("flow_control") == "on"
    ingress_filtering_enabled = request.form.get("ingress_filtering") == "on"
    vlan_trunk_enabled = request.form.get("vlan_trunk") == "on"

    current_alias = request.form.get("current_alias", port.alias or "")
    current_admin_enabled = request.form.get("current_admin", "1" if port.admin_enabled else "0") == "1"
    current_speed_code = request.form.get("current_speed", "0")
    current_duplex_code = request.form.get("current_duplex", "0")
    current_pvid_raw = request.form.get("current_pvid", str(port.vlan_id or 1)).strip()
    current_pvid = int(current_pvid_raw) if current_pvid_raw.isdigit() else int(port.vlan_id or 1)
    current_frame_type_code = request.form.get("current_frame_type", "0")
    current_flow_control_enabled = request.form.get("current_flow_control", "0") == "1"
    current_ingress_filtering_enabled = request.form.get("current_ingress_filtering", "0") == "1"
    current_vlan_trunk_enabled = request.form.get("current_vlan_trunk", "0") == "1"

    pvid_raw = (request.form.get("pvid") or str(current_pvid)).strip()
    if not pvid_raw.isdigit():
        raise RuntimeError(f"Ungueltige PVID: {pvid_raw}")
    pvid = int(pvid_raw)
    if pvid < 1 or pvid > 4094:
        raise RuntimeError(f"PVID ausserhalb des gueltigen Bereichs: {pvid}")

    memberships: dict[int, str] = {}
    for field_name, raw_membership in request.form.items():
        if not field_name.startswith("membership_"):
            continue
        vlan_id_raw = field_name.split("_", 1)[1]
        if not vlan_id_raw.isdigit():
            continue
        vlan_id = int(vlan_id_raw)
        memberships[vlan_id] = _parse_zyxel_choice(
            raw_membership,
            {"0", "1", "2", "3"},
            field=f"VLAN-Mitgliedschaft {vlan_id}",
            default="0",
        )

    current_memberships = _read_zyxel_memberships(device, port.port_number)
    if not memberships:
        memberships = dict(current_memberships)

    untagged_count = len([code for code in memberships.values() if code == "3"])
    if untagged_count > 1:
        raise RuntimeError("Ein Zyxel-Port darf nur in genau einem VLAN als untagged Mitglied laufen.")

    physical_changed = (
        alias != current_alias
        or admin_enabled != current_admin_enabled
        or speed_code != current_speed_code
        or duplex_code != current_duplex_code
        or flow_control_enabled != current_flow_control_enabled
    )
    vlan_settings_changed = (
        pvid != current_pvid
        or frame_type_code != current_frame_type_code
        or ingress_filtering_enabled != current_ingress_filtering_enabled
        or vlan_trunk_enabled != current_vlan_trunk_enabled
    )
    changed_memberships = {
        vlan_id: code
        for vlan_id, code in memberships.items()
        if current_memberships.get(vlan_id, "0") != code
    }

    result: dict[str, object] = {"saved": False}
    if physical_changed:
        result["physical"] = client.set_port_physical(
            port.port_number,
            alias=alias,
            admin_enabled=admin_enabled,
            speed_code=speed_code,
            duplex_code=duplex_code,
            flow_control_enabled=flow_control_enabled,
            save=False,
        )
    if vlan_settings_changed:
        result["vlan"] = client.set_port_vlan_settings(
            port.port_number,
            pvid=pvid,
            frame_type_code=frame_type_code,
            ingress_filtering_enabled=ingress_filtering_enabled,
            vlan_trunk_enabled=vlan_trunk_enabled,
            save=False,
        )
    if changed_memberships:
        result["memberships"] = client.set_port_memberships(port.port_number, changed_memberships, save=False)

    if physical_changed or vlan_settings_changed or changed_memberships:
        client.save_config()
        result["saved"] = True

    inventory_vlan_id, inventory_vlan_mode = _derive_zyxel_inventory(memberships, pvid)
    return {
        "alias": alias,
        "admin_enabled": admin_enabled,
        "speed_code": speed_code,
        "duplex_code": duplex_code,
        "flow_control_enabled": flow_control_enabled,
        "pvid": pvid,
        "frame_type_code": frame_type_code,
        "ingress_filtering_enabled": ingress_filtering_enabled,
        "vlan_trunk_enabled": vlan_trunk_enabled,
        "memberships": memberships,
        "result": result,
    }, inventory_vlan_id, inventory_vlan_mode


def _apply_port_changes(driver, port: Port, *, alias: str, admin_enabled: bool, vlan_id: int, vlan_mode: str, poe_enabled: bool) -> bool:
    applied = False
    if vlan_id != port.vlan_id or vlan_mode != port.vlan_mode:
        driver.assign_port_to_vlan(port.port_number, vlan_id, vlan_mode, dry_run=False)
        applied = True
    if admin_enabled != port.admin_enabled:
        driver.set_port_admin_state(port.port_number, admin_enabled, dry_run=False)
        applied = True
    if poe_enabled != port.poe_enabled:
        driver.set_poe_state(port.port_number, poe_enabled, dry_run=False)
        applied = True
    if alias != (port.alias or ""):
        driver.set_port_alias(port.port_number, alias, dry_run=False)
        applied = True
    return applied


def _validate_poe_change(driver, port_number: int, current_enabled: bool, desired_enabled: bool) -> None:
    if desired_enabled == current_enabled:
        return
    if desired_enabled and not driver.supports_poe_port(port_number):
        reason = driver.poe_support_reason(port_number) or f"PoE wird auf Port {port_number} nicht unterstuetzt."
        raise RuntimeError(reason)


def _apply_edgeos_port_changes(
    driver,
    port: Port,
    *,
    alias: str,
    admin_enabled: bool,
    vlan_id: int,
    vlan_mode: str,
    poe_enabled: bool,
    switch_name: str | None,
    tagged_vlans: list[int],
    remove_l3_vifs: bool,
) -> bool:
    applied = False
    if vlan_mode == "excluded":
        driver.configure_switch_port(
            port.port_number,
            profile="routed",
            native_vlan=None,
            tagged_vlans=[],
            switch_name=switch_name or None,
            remove_l3_vifs=False,
            dry_run=False,
        )
        applied = True
    else:
        native_vlan = None if vlan_mode == "tagged" else vlan_id
        desired_tagged = list(tagged_vlans)
        if vlan_mode == "tagged" and vlan_id not in desired_tagged:
            desired_tagged.insert(0, vlan_id)
        driver.configure_switch_port(
            port.port_number,
            profile="switch-port",
            native_vlan=native_vlan,
            tagged_vlans=desired_tagged,
            switch_name=switch_name or None,
            remove_l3_vifs=remove_l3_vifs,
            dry_run=False,
        )
        applied = True
    if admin_enabled != port.admin_enabled:
        driver.set_port_admin_state(port.port_number, admin_enabled, dry_run=False)
        applied = True
    if poe_enabled != port.poe_enabled:
        driver.set_poe_state(port.port_number, poe_enabled, dry_run=False)
        applied = True
    if alias != (port.alias or ""):
        driver.set_port_alias(port.port_number, alias, dry_run=False)
        applied = True
    return applied


def _flatten_result_output(result: dict | None) -> str:
    if not result:
        return ""
    outputs = result.get("output") or []
    if isinstance(outputs, str):
        return outputs.strip()

    chunks: list[str] = []
    for item in outputs:
        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned:
                chunks.append(cleaned)
        elif item:
            chunks.append(str(item))
    return "\n\n".join(chunks).strip()


def _split_command_lines(raw: str) -> list[str]:
    lines: list[str] = []
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        lines.append(stripped)
    return lines


@bp.route("/")
@login_required
def index():
    devices = Device.query.order_by(Device.name.asc()).all()
    all_ports = Port.query.all()
    filters = {
        "q": (request.args.get("q") or "").strip().lower(),
        "status": (request.args.get("status") or "all").lower(),
        "sort": (request.args.get("sort") or "name").lower(),
        "view": (request.args.get("view") or "table").lower(),
    }

    filtered = []
    for device in devices:
        if filters["q"] and filters["q"] not in f"{device.name} {device.host} {device.model}".lower():
            continue
        if filters["status"] != "all" and device.status != filters["status"]:
            continue
        filtered.append(device)

    if filters["sort"] == "status":
        filtered.sort(key=lambda d: (d.status, d.name.lower()))
    elif filters["sort"] == "model":
        filtered.sort(key=lambda d: (d.model.lower(), d.name.lower()))
    elif filters["sort"] == "ip":
        filtered.sort(key=lambda d: d.host)
    else:
        filtered.sort(key=lambda d: d.name.lower())

    favorites = filtered[:5]
    device_cards = []
    for device in filtered:
        device_ports = [port for port in all_ports if port.device_id == device.id]
        device_cards.append({
            "device": device,
            "ports_total": len(device_ports),
            "ports_up": len([port for port in device_ports if port.link_state == "up" and port.admin_enabled]),
            "ports_disabled": len([port for port in device_ports if not port.admin_enabled]),
            "warnings": len([port for port in device_ports if port.link_state == "down" and port.admin_enabled]),
        })
    return render_template("devices/index.html", devices=filtered, filters=filters, favorites=favorites, device_cards=device_cards)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = DeviceForm()
    if form.validate_on_submit():
        device = Device(
            name=form.name.data,
            host=form.host.data,
            ssh_port=form.ssh_port.data,
            username=form.username.data,
            password=form.password.data,
            key_path=(form.key_path.data or None),
            driver_type=form.driver_type.data,
            model=form.model.data or "Unbekannt",
        )
        db.session.add(device)
        db.session.commit()
        ensure_device_inventory(device, form.inventory_port_count.data)
        write_audit(current_user.username, "device_create", device.name, f"Device {device.host} erstellt", "success")
        flash("Gerät gespeichert.", "success")
        return redirect(url_for("devices.detail", device_id=device.id))
    return render_template("devices/form.html", form=form, title="Switch hinzufügen")


@bp.route("/<int:device_id>")
@login_required
def detail(device_id: int):
    device = Device.query.get_or_404(device_id)
    set_selected_device(device.id)

    ensure_device_inventory(device)
    snapshot = None
    snapshot_errors: list[str] = []
    try:
        snapshot = load_device_center_snapshot(device)
    except Exception as exc:  # noqa: BLE001
        snapshot_errors.append(f"Live-Telemetrie konnte nicht geladen werden: {exc}")

    ports = Port.query.filter_by(device_id=device.id).order_by(Port.port_number.asc()).all()
    vlans = VLAN.query.filter_by(device_id=device.id).order_by(VLAN.vlan_id.asc()).all()
    profiles = NetworkProfile.query.order_by(NetworkProfile.name.asc()).all()
    events = AuditLog.query.filter(AuditLog.target == device.name).order_by(AuditLog.created_at.desc()).limit(18).all()
    capability_catalog = get_capability_catalog(device.driver_type)
    module_cards = [
        {
            "title": "Observe",
            "description": "Traffic, MAC, ARP, LLDP und Discovery in einer operativen Ansicht.",
            "href": url_for("observe.device", device_id=device.id),
            "cta": "Live-Ansicht",
        },
        {
            "title": "Ports",
            "description": "Ports als klickbare Matrix mit Bulk-Aktionen, Profilen und Health-Signalen.",
            "href": url_for("ports.index"),
            "cta": "Ports steuern",
        },
        {
            "title": "Networks",
            "description": "Segmente, VLANs und Profile in einer zusammenhängenden Netzwerksicht.",
            "href": url_for("networks.index"),
            "cta": "Netze öffnen",
        },
        {
            "title": "Live Config",
            "description": "Running-Config und Live-Interfaces mit lesbarer Struktur.",
            "href": url_for("devices.live_config", device_id=device.id),
            "cta": "Konfig lesen",
        },
        {
            "title": "Advanced Config",
            "description": "Tiefer Eingriff für Bereiche, die noch nicht als eigene Klick-Oberfläche modelliert sind.",
            "href": url_for("devices.advanced", device_id=device.id),
            "cta": "Erweitert",
        },
        {
            "title": "Maintenance",
            "description": "Backup, Save, Reboot und Wartungsabläufe zentral auslösen.",
            "href": url_for("system.index"),
            "cta": "Wartung",
        },
    ]

    stats = {
        "port_total": len(ports),
        "port_up": len([p for p in ports if p.link_state == "up" and p.admin_enabled]),
        "port_down": len([p for p in ports if p.link_state == "down" and p.admin_enabled]),
        "port_disabled": len([p for p in ports if not p.admin_enabled]),
        "poe_on": len([p for p in ports if p.poe_enabled]),
    }
    return render_template(
        "devices/detail.html",
        device=device,
        ports=ports,
        vlans=vlans,
        profiles=profiles,
        events=events,
        stats=stats,
        snapshot=snapshot,
        snapshot_errors=snapshot_errors,
        capability_catalog=capability_catalog,
        module_cards=module_cards,
    )


@bp.route("/<int:device_id>/config")
@login_required
def live_config(device_id: int):
    device = Device.query.get_or_404(device_id)
    set_selected_device(device.id)

    driver = get_driver(device)
    interfaces: list[dict] = []
    live_vlans: list[dict] = []
    running_config = ""
    live_info: dict = {}
    warnings: list[str] = []

    try:
        driver.connect()

        try:
            live_info = driver.get_system_info()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Systeminformationen konnten nicht gelesen werden: {exc}")

        try:
            interfaces = driver.get_interfaces()
            apply_interface_snapshot(device, interfaces)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Interfaces konnten nicht gelesen werden: {exc}")

        try:
            live_vlans = driver.get_vlans()
            apply_vlan_snapshot(device, live_vlans)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"VLANs konnten nicht gelesen werden: {exc}")

        try:
            backup = driver.backup_config(dry_run=False)
            running_config = _flatten_result_output(backup)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Running-Config konnte nicht gelesen werden: {exc}")

        if live_info.get("model"):
            device.model = str(live_info["model"])
        if live_info.get("firmware"):
            device.firmware = str(live_info["firmware"])
        if live_info.get("mgmt_ip"):
            device.mgmt_ip = str(live_info["mgmt_ip"])
        device.status = "online"
        device.last_seen_at = datetime.utcnow()
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        device.status = "offline"
        db.session.commit()
        warnings.append(f"Live-Konfiguration konnte nicht geladen werden: {exc}")
    finally:
        driver.close()

    stored_ports = Port.query.filter_by(device_id=device.id).order_by(Port.port_number.asc()).all()
    stored_vlans = VLAN.query.filter_by(device_id=device.id).order_by(VLAN.vlan_id.asc()).all()
    events = AuditLog.query.filter(AuditLog.target == device.name).order_by(AuditLog.created_at.desc()).limit(50).all()

    return render_template(
        "devices/config.html",
        device=device,
        live_info=live_info,
        interfaces=interfaces if interfaces else stored_ports,
        live_vlans=live_vlans if live_vlans else stored_vlans,
        running_config=running_config,
        warnings=warnings,
        events=events,
    )


@bp.route("/<int:device_id>/advanced", methods=["GET", "POST"])
@login_required
def advanced(device_id: int):
    device = Device.query.get_or_404(device_id)
    set_selected_device(device.id)

    result = None
    warnings: list[str] = []
    running_config = ""
    command_config = ""
    live_info: dict = {}
    submitted_commands = ""

    if request.method == "POST":
        submitted_commands = request.form.get("commands", "")
        if request.form.get("action") == "expert_commands":
            commands = _split_command_lines(submitted_commands)
            dry_run = request.form.get("dry_run", "1") == "1"
            driver = get_driver(device)
            try:
                if not hasattr(driver, "execute_expert_commands"):
                    raise RuntimeError(
                        "Dieses Geraet nutzt fuer Vollkonfiguration die native Web-Bridge. "
                        "Direkte Expertenbefehle sind hier nicht verfuegbar."
                    )

                if not dry_run:
                    driver.connect()

                result = driver.execute_expert_commands(commands, dry_run=dry_run)
                flash(
                    "EdgeOS-Befehle als Vorschau erzeugt." if dry_run else "EdgeOS-Befehle ausgefuehrt.",
                    "success",
                )
                write_audit(
                    current_user.username,
                    "device_expert_commands",
                    device.name,
                    str(result.get("commands", [])),
                    "success",
                )
            except Exception as exc:  # noqa: BLE001
                result = {"dry_run": dry_run, "commands": commands, "output": [str(exc)]}
                flash(f"Expertenbefehle fehlgeschlagen: {exc}", "error")
                write_audit(
                    current_user.username,
                    "device_expert_commands",
                    device.name,
                    "Expertenbefehle fehlgeschlagen",
                    "failed",
                    str(exc),
                )
            finally:
                driver.close()

    driver = get_driver(device)
    try:
        driver.connect()

        try:
            live_info = driver.get_system_info()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Systeminformationen konnten nicht gelesen werden: {exc}")

        try:
            backup = driver.backup_config(dry_run=False)
            running_config = _flatten_result_output(backup)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Running-Config konnte nicht gelesen werden: {exc}")

        if hasattr(driver, "get_config_commands"):
            try:
                command_config = str(driver.get_config_commands()).strip()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Konfigurationsbefehle konnten nicht gelesen werden: {exc}")

        if live_info.get("model"):
            device.model = str(live_info["model"])
        if live_info.get("firmware"):
            device.firmware = str(live_info["firmware"])
        if live_info.get("mgmt_ip"):
            device.mgmt_ip = str(live_info["mgmt_ip"])

        device.status = "online"
        device.last_seen_at = datetime.utcnow()
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        device.status = "offline"
        db.session.commit()
        warnings.append(f"Advanced-Konfiguration konnte nicht geladen werden: {exc}")
    finally:
        driver.close()

    config_sections = build_config_sections(device.driver_type, running_config, command_config)
    capabilities = get_capability_catalog(device.driver_type)
    native_proxy_url = None
    if device.driver_type == "zyxel-ssh":
        native_proxy_url = url_for("devices.zyxel_native_proxy", device_id=device.id, proxy_path="cgi-bin/dispatcher.cgi", cmd=1)

    return render_template(
        "devices/advanced.html",
        device=device,
        live_info=live_info,
        warnings=warnings,
        running_config=running_config,
        command_config=command_config,
        config_sections=config_sections,
        capabilities=capabilities,
        result=result,
        submitted_commands=submitted_commands,
        native_proxy_url=native_proxy_url,
    )


@bp.route("/<int:device_id>/native/zyxel", defaults={"proxy_path": ""}, methods=["GET", "POST"])
@bp.route("/<int:device_id>/native/zyxel/<path:proxy_path>", methods=["GET", "POST"])
@csrf.exempt
@login_required
def zyxel_native_proxy(device_id: int, proxy_path: str):
    device = Device.query.get_or_404(device_id)
    if device.driver_type != "zyxel-ssh":
        abort(404)

    if not proxy_path:
        return redirect(url_for("devices.zyxel_native_proxy", device_id=device.id, proxy_path="cgi-bin/dispatcher.cgi", cmd=1))

    proxy_root = url_for("devices.zyxel_native_proxy", device_id=device.id, proxy_path="")
    proxied = proxy_zyxel_request(
        cache_key=f"{current_user.get_id()}:{device.id}",
        host=device.host,
        username=device.username,
        password=device.password or "",
        proxy_root=proxy_root,
        proxy_path=proxy_path,
        method=request.method,
        query_string=request.query_string,
        body=request.get_data() if request.method != "GET" else None,
        content_type=request.headers.get("Content-Type"),
    )

    excluded_headers = {
        "content-length",
        "content-encoding",
        "transfer-encoding",
        "connection",
        "x-frame-options",
        "content-security-policy",
        "strict-transport-security",
        "set-cookie",
    }
    headers = [
        (key, value)
        for key, value in proxied.headers.items()
        if key.lower() not in excluded_headers
    ]
    headers.append(("Cache-Control", "no-store"))
    return Response(proxied.content, status=proxied.status_code, headers=headers)


@bp.route("/<int:device_id>/port/<int:port_id>/update", methods=["POST"])
@login_required
def update_port(device_id: int, port_id: int):
    device = Device.query.get_or_404(device_id)
    port = Port.query.filter_by(device_id=device.id, id=port_id).first_or_404()

    new_alias = request.form.get("alias", port.alias)
    new_vlan_id = int(request.form.get("vlan_id", port.vlan_id))
    new_vlan_mode = request.form.get("vlan_mode", port.vlan_mode)
    new_admin_enabled = request.form.get("admin_enabled") == "on"
    new_poe_enabled = request.form.get("poe_enabled") == "on"
    new_switch_name = (request.form.get("switch_name") or "").strip()
    new_tagged_vlans = _parse_vlan_csv(request.form.get("tagged_vlans"))
    remove_l3_vifs = request.form.get("remove_l3_vifs") == "on"
    edgeos_profile_requested = device.driver_type == "edgeos-ssh" and (
        "switch_name" in request.form or "tagged_vlans" in request.form or new_vlan_mode == "excluded"
    )

    driver = get_driver(device)
    try:
        if device.driver_type == "zyxel-ssh":
            applied_state, inventory_vlan_id, inventory_vlan_mode = _apply_zyxel_port_changes(device, port)

            port.alias = applied_state["alias"]
            port.admin_enabled = applied_state["admin_enabled"]
            port.speed = PORT_SPEED_LABELS.get(applied_state["speed_code"], "Auto")
            port.duplex = PORT_DUPLEX_LABELS.get(applied_state["duplex_code"], "Auto")
            port.vlan_id = inventory_vlan_id
            port.vlan_mode = inventory_vlan_mode
            port.poe_enabled = False
            db.session.commit()

            write_audit(
                current_user.username,
                "port_update",
                device.name,
                (
                    f"Port {port.port_number}: alias={port.alias}, admin={port.admin_enabled}, "
                    f"pvid={applied_state['pvid']}, vlan_mode={port.vlan_mode}"
                ),
                "success",
            )
            flash(f"Port {port.port_number} nativ auf dem Zyxel gespeichert.", "success")
            return redirect(url_for("devices.detail", device_id=device.id, tab="ports", selected_port=port.id))

        if (
            new_alias != (port.alias or "")
            or new_admin_enabled != port.admin_enabled
            or new_vlan_id != port.vlan_id
            or new_vlan_mode != port.vlan_mode
            or new_poe_enabled != port.poe_enabled
            or edgeos_profile_requested
        ):
            driver.connect()
            _validate_poe_change(driver, port.port_number, port.poe_enabled, new_poe_enabled)
            if edgeos_profile_requested:
                _apply_edgeos_port_changes(
                    driver,
                    port,
                    alias=new_alias,
                    admin_enabled=new_admin_enabled,
                    vlan_id=new_vlan_id,
                    vlan_mode=new_vlan_mode,
                    poe_enabled=new_poe_enabled,
                    switch_name=new_switch_name,
                    tagged_vlans=new_tagged_vlans,
                    remove_l3_vifs=remove_l3_vifs,
                )
            else:
                _apply_port_changes(
                    driver,
                    port,
                    alias=new_alias,
                    admin_enabled=new_admin_enabled,
                    vlan_id=new_vlan_id,
                    vlan_mode=new_vlan_mode,
                    poe_enabled=new_poe_enabled,
                )

        port.alias = new_alias
        if edgeos_profile_requested and new_vlan_mode == "excluded":
            port.vlan_id = 1
            port.vlan_mode = "routed"
        else:
            port.vlan_id = new_vlan_id
            port.vlan_mode = new_vlan_mode
        port.admin_enabled = new_admin_enabled
        port.poe_enabled = new_poe_enabled
        db.session.commit()

        write_audit(
            current_user.username,
            "port_update",
            device.name,
            f"Port {port.port_number}: VLAN {port.vlan_id}/{port.vlan_mode}, admin={port.admin_enabled}, poe={port.poe_enabled}",
            "success",
        )
        flash(f"Port {port.port_number} aktualisiert und auf Gerät übernommen.", "success")
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        write_audit(current_user.username, "port_update", device.name, "Port-Update fehlgeschlagen", "failed", str(exc))
        flash(f"Port-Update fehlgeschlagen: {exc}", "error")
    finally:
        driver.close()
    return redirect(url_for("devices.detail", device_id=device.id, tab="ports", selected_port=port.id))


@bp.route("/<int:device_id>/action/<string:action>", methods=["POST"])
@login_required
def action(device_id: int, action: str):
    device = Device.query.get_or_404(device_id)

    if action == "sync":
        driver = get_driver(device)
        try:
            driver.connect()
            synced_interfaces = 0
            synced_vlans = 0
            try:
                info = driver.get_system_info()
                raw_info = str(info.get("raw", ""))
                model = info.get("model") or _extract_value(raw_info, ["model"]) or _extract_value(raw_info, ["product model"])
                firmware = info.get("firmware") or _extract_value(raw_info, ["firmware", "version"])
                mgmt_ip = info.get("mgmt_ip") or _extract_value(raw_info, ["management ip", "ip address"])
                if model:
                    device.model = model
                if firmware:
                    device.firmware = firmware
                if mgmt_ip:
                    device.mgmt_ip = mgmt_ip
            except Exception:  # noqa: BLE001
                pass

            try:
                interfaces = driver.get_interfaces()
                synced_interfaces = apply_interface_snapshot(device, interfaces)
            except Exception:  # noqa: BLE001
                synced_interfaces = 0

            try:
                vlans = driver.get_vlans()
                synced_vlans = apply_vlan_snapshot(device, vlans)
            except Exception:  # noqa: BLE001
                synced_vlans = 0

            if synced_interfaces == 0:
                try:
                    setting = AppSetting.query.filter_by(section="controller", key="snmp_community").first()
                    community = setting.value.strip() if setting and setting.value else None
                    snmp_rows = probe_interface_states(device.host, community=community, timeout=2)
                except Exception:  # noqa: BLE001
                    snmp_rows = []
                if snmp_rows:
                    synced_interfaces = apply_interface_snapshot(device, snmp_rows)

            created_ports, total_ports = ensure_device_inventory(device)
            device.status = "online"
            device.last_seen_at = datetime.utcnow()
            db.session.commit()

            details = f"Sync ok: interfaces={synced_interfaces}, vlans={synced_vlans}, created_ports={created_ports}, total_ports={total_ports}"
            write_audit(current_user.username, "device_sync", device.name, details, "success")
            if synced_interfaces:
                flash(f"Synchronisierung erfolgreich ({synced_interfaces} Interfaces, {synced_vlans} VLANs).", "success")
            else:
                flash(f"Gerät erreichbar, aber es wurden keine Interface-Daten gelesen. VLANs aktualisiert: {synced_vlans}.", "warning")
        except Exception as exc:  # noqa: BLE001
            device.status = "offline"
            db.session.commit()
            write_audit(current_user.username, "device_sync", device.name, "Synchronisierung fehlgeschlagen", "failed", str(exc))
            flash(f"Synchronisierung fehlgeschlagen: {exc}", "error")
        finally:
            driver.close()
    elif action == "reconnect":
        driver = get_driver(device)
        try:
            driver.connect()
            device.status = "online"
            device.last_seen_at = datetime.utcnow()
            db.session.commit()
            flash("Reconnect erfolgreich.", "success")
            write_audit(current_user.username, "device_reconnect", device.name, "Reconnect erfolgreich", "success")
        except Exception as exc:  # noqa: BLE001
            device.status = "offline"
            db.session.commit()
            flash(f"Reconnect fehlgeschlagen: {exc}", "error")
            write_audit(current_user.username, "device_reconnect", device.name, "Reconnect fehlgeschlagen", "failed", str(exc))
        finally:
            driver.close()
        return redirect(url_for("devices.detail", device_id=device.id))
    elif action == "remove":
        name = device.name
        db.session.delete(device)
        db.session.commit()
        write_audit(current_user.username, "device_delete", name, "Gerät entfernt", "success")
        flash("Gerät entfernt.", "success")
        return redirect(url_for("devices.index"))

    return redirect(url_for("devices.detail", device_id=device.id))


@bp.route("/<int:device_id>/edit", methods=["GET", "POST"])
@login_required
def edit(device_id: int):
    device = Device.query.get_or_404(device_id)
    form = DeviceForm(obj=device)
    if form.validate_on_submit():
        device.name = form.name.data
        device.host = form.host.data
        device.ssh_port = form.ssh_port.data
        device.username = form.username.data
        device.driver_type = form.driver_type.data
        device.model = form.model.data or device.model or "Unbekannt"

        # Passwort nur überschreiben, wenn explizit neu gesetzt.
        if (form.password.data or "").strip():
            device.password = form.password.data

        # Key-Pfad nur ändern, wenn ein Wert eingegeben wurde.
        if form.key_path.data is not None and (form.key_path.data or "").strip():
            device.key_path = form.key_path.data.strip()

        device.key_path = (device.key_path or "").strip() or None
        ensure_device_inventory(device, form.inventory_port_count.data)
        db.session.commit()
        write_audit(current_user.username, "device_edit", device.name, "Gerät bearbeitet", "success")
        flash("Gerät aktualisiert.", "success")
        return redirect(url_for("devices.detail", device_id=device.id))
    return render_template("devices/form.html", form=form, title=f"Gerät bearbeiten: {device.name}")


@bp.route("/<int:device_id>/delete", methods=["POST"])
@login_required
def delete(device_id: int):
    device = Device.query.get_or_404(device_id)
    name = device.name
    db.session.delete(device)
    db.session.commit()
    write_audit(current_user.username, "device_delete", name, "Gerät entfernt", "success")
    flash("Gerät gelöscht.", "success")
    return redirect(url_for("devices.index"))


@bp.route("/<int:device_id>/test", methods=["POST"])
@login_required
def test_connection(device_id: int):
    device = Device.query.get_or_404(device_id)
    driver = get_driver(device)
    try:
        driver.connect()
        device.status = "online"
        device.last_seen_at = datetime.utcnow()
        db.session.commit()
        flash("Verbindung erfolgreich.", "success")
        write_audit(current_user.username, "device_test", device.name, "SSH Verbindung erfolgreich", "success")
    except Exception as exc:  # noqa: BLE001
        device.status = "offline"
        db.session.commit()
        flash(f"Verbindung fehlgeschlagen: {exc}", "error")
        write_audit(current_user.username, "device_test", device.name, "SSH Verbindung fehlgeschlagen", "failed", str(exc))
    finally:
        driver.close()
    return redirect(request.referrer or url_for("devices.index"))


@bp.route("/<int:device_id>/select", methods=["GET", "POST"])
@login_required
def select(device_id: int):
    device = Device.query.get_or_404(device_id)
    set_selected_device(device.id)
    flash(f"Aktives Gerät: {device.name}", "success")
    return redirect(request.referrer or url_for("dashboard.index"))
