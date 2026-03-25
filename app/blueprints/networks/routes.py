from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.network_profile_forms import NetworkProfileForm
from app.models.models import Device, NetworkProfile
from app.services.audit_service import write_audit
from app.services.command_builder import CommandAction, CommandBuilder
from app.utils.device_context import get_selected_device
from app.utils.driver_factory import get_driver

bp = Blueprint("networks", __name__, url_prefix="/networks")


@bp.route("/")
@login_required
def index():
    profiles = NetworkProfile.query.order_by(NetworkProfile.updated_at.desc()).all()
    return render_template("networks/index.html", profiles=profiles)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = NetworkProfileForm()
    preview = None
    if form.validate_on_submit():
        profile = NetworkProfile()
        form.populate_obj(profile)
        db.session.add(profile)
        db.session.commit()
        preview = CommandBuilder.build(CommandAction("apply_network_profile", _profile_to_payload(profile)))
        flash("Netzwerkprofil erstellt. Vorschau verfügbar.", "success")
        write_audit(current_user.username, "network_profile_create", profile.name, "Profil erstellt", "success")
        return render_template("networks/form.html", form=form, preview=preview, profile=profile)
    return render_template("networks/form.html", form=form, preview=preview, profile=None)


@bp.route("/<int:profile_id>/edit", methods=["GET", "POST"])
@login_required
def edit(profile_id: int):
    profile = NetworkProfile.query.get_or_404(profile_id)
    form = NetworkProfileForm(obj=profile)
    preview = None
    if form.validate_on_submit():
        form.populate_obj(profile)
        db.session.commit()
        preview = CommandBuilder.build(CommandAction("apply_network_profile", _profile_to_payload(profile)))
        flash("Netzwerkprofil aktualisiert.", "success")
        write_audit(current_user.username, "network_profile_update", profile.name, "Profil aktualisiert", "success")
    return render_template("networks/form.html", form=form, preview=preview, profile=profile)


@bp.route("/<int:profile_id>/apply", methods=["POST"])
@login_required
def apply(profile_id: int):
    profile = NetworkProfile.query.get_or_404(profile_id)
    device = get_selected_device()
    dry_run = request.form.get("dry_run", "1") == "1"
    commands = CommandBuilder.build(CommandAction("apply_network_profile", _profile_to_payload(profile)))

    if not device:
        flash("Kein Gerät gefunden. Nur Vorschau möglich.", "warning")
        return redirect(url_for("networks.edit", profile_id=profile.id))

    driver = get_driver(device)
    try:
        result = driver._run(commands, dry_run=dry_run)
        flash("Profil angewendet." if not dry_run else "Dry-Run Vorschau erstellt.", "success")
        write_audit(current_user.username, "network_profile_apply", device.name, str(commands), "success")
    except Exception as exc:  # noqa: BLE001
        flash(str(exc), "error")
        write_audit(current_user.username, "network_profile_apply", device.name, "Profil-Anwendung fehlgeschlagen", "failed", str(exc))
    finally:
        driver.close()
    return redirect(url_for("networks.edit", profile_id=profile.id))


def _profile_to_payload(profile: NetworkProfile) -> dict:
    return {
        "name": profile.name,
        "purpose": profile.purpose,
        "vlan_id": profile.vlan_id,
        "gateway_ip": profile.gateway_ip,
        "subnet_mask": profile.subnet_mask,
        "dhcp_enabled": profile.dhcp_enabled,
        "dhcp_start": profile.dhcp_start,
        "dhcp_end": profile.dhcp_end,
        "dhcp_lease_time": profile.dhcp_lease_time,
        "dns_primary": profile.dns_primary,
        "dns_secondary": profile.dns_secondary,
        "igmp_snooping": profile.igmp_snooping,
        "dhcp_guarding": profile.dhcp_guarding,
        "upnp_lan": profile.upnp_lan,
        "multicast_dns": profile.multicast_dns,
    }
