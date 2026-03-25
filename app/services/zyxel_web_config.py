from __future__ import annotations

from html.parser import HTMLParser

from app.services.zyxel_native_proxy import _get_or_create_session, _login, _looks_like_login_page


PORT_SPEED_LABELS = {
    "0": "Auto",
    "1": "10M",
    "2": "100M",
    "3": "1000M",
}

PORT_DUPLEX_LABELS = {
    "0": "Auto",
    "1": "Full",
    "2": "Half",
}

FRAME_TYPE_LABELS = {
    "0": "All",
    "1": "Tag Only",
    "2": "Untag Only",
}

MEMBERSHIP_LABELS = {
    "0": "Excluded",
    "1": "Forbidden",
    "2": "Tagged",
    "3": "Untagged",
}


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[dict[str, str]] = []
        self.selects: dict[str, dict[str, object]] = {}
        self._active_select_name: str | None = None
        self._active_option: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: "" if value is None else value for key, value in attrs}
        if tag == "input":
            self.inputs.append(attr_map)
            return
        if tag == "select":
            select_name = attr_map.get("name") or attr_map.get("id")
            if select_name:
                self._active_select_name = select_name
                self.selects[select_name] = {"attrs": attr_map, "options": []}
            return
        if tag == "option" and self._active_select_name:
            self._active_option = {"attrs": attr_map, "text": ""}

    def handle_data(self, data: str) -> None:
        if self._active_option is not None:
            self._active_option["text"] = f"{self._active_option['text']}{data}"

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self._active_select_name and self._active_option is not None:
            select_data = self.selects.get(self._active_select_name)
            if select_data:
                options = select_data.setdefault("options", [])
                assert isinstance(options, list)
                options.append(self._active_option)
            self._active_option = None
            return
        if tag == "select":
            self._active_option = None
            self._active_select_name = None


def _parse_document(html: str) -> _DocumentParser:
    parser = _DocumentParser()
    parser.feed(html)
    return parser


def _input_value(inputs: list[dict[str, str]], name: str, default: str = "") -> str:
    for item in inputs:
        if item.get("name") == name:
            return item.get("value", default)
    return default


def _checked_radio_value(inputs: list[dict[str, str]], name: str, default: str = "") -> str:
    for item in inputs:
        if item.get("name") == name and item.get("type") == "radio" and "checked" in item:
            return item.get("value", default)
    return default


def _selected_option_value(selects: dict[str, dict[str, object]], name: str, default: str = "") -> str:
    select_data = selects.get(name)
    if not select_data:
        return default

    options = select_data.get("options") or []
    assert isinstance(options, list)
    for option in options:
        if isinstance(option, dict) and "selected" in (option.get("attrs") or {}):
            attrs = option.get("attrs") or {}
            assert isinstance(attrs, dict)
            return str(attrs.get("value", default))

    if options and isinstance(options[0], dict):
        attrs = options[0].get("attrs") or {}
        assert isinstance(attrs, dict)
        return str(attrs.get("value", default))
    return default


class ZyxelWebConfigClient:
    def __init__(self, host: str, username: str, password: str | None):
        self.host = host
        self.username = username
        self.password = password or ""
        self._session = None
        self._base_url = ""
        self._cache_key = f"zyxel-config::{host}::{username}"

    def _ensure_session(self) -> None:
        if self._session is None or not self._base_url:
            state = _get_or_create_session(self._cache_key, self.host, self.username, self.password)
            self._session = state.session
            self._base_url = state.base_url

    def _request(self, method: str, *, params: dict[str, object] | None = None, data: dict[str, object] | None = None):
        self._ensure_session()
        assert self._session is not None

        request_fn = self._session.get if method.upper() == "GET" else self._session.post
        response = request_fn(
            f"{self._base_url}/cgi-bin/dispatcher.cgi",
            params=params,
            data=data,
            timeout=20,
            verify=False,
        )

        if _looks_like_login_page(response):
            self._session, self._base_url = _login(self.host, self.username, self.password)
            request_fn = self._session.get if method.upper() == "GET" else self._session.post
            response = request_fn(
                f"{self._base_url}/cgi-bin/dispatcher.cgi",
                params=params,
                data=data,
                timeout=20,
                verify=False,
            )

        if response.status_code >= 400:
            raise RuntimeError(f"Zyxel-Webrequest fehlgeschlagen ({response.status_code}).")
        return response

    def save_config(self) -> dict:
        self._request("GET", params={"cmd": 6})
        return {"saved": True, "command": "GET /cgi-bin/dispatcher.cgi?cmd=6"}

    def set_port_physical(
        self,
        port_number: int,
        *,
        alias: str | None = None,
        admin_enabled: bool | None = None,
        speed_code: str | None = None,
        duplex_code: str | None = None,
        flow_control_enabled: bool | None = None,
        save: bool = True,
    ) -> dict:
        physical = self._load_port_physical_form(port_number)
        resolved_alias = alias if alias is not None else str(physical["alias"])
        resolved_admin = bool(physical["state_code"] == "1") if admin_enabled is None else bool(admin_enabled)
        resolved_speed = str(speed_code if speed_code is not None else physical["speed_code"])
        resolved_duplex = str(duplex_code if duplex_code is not None else physical["duplex_code"])
        resolved_flow = bool(physical["flow_control_code"] == "1") if flow_control_enabled is None else bool(flow_control_enabled)

        self._request(
            "POST",
            data={
                "XSSID": physical["xssid"],
                "portlist": physical["portlist"],
                "cmd": 770,
                "descp": resolved_alias[:32],
                "state": "1" if resolved_admin else "0",
                "speed": resolved_speed,
                "duplex": resolved_duplex,
                "fc": "1" if resolved_flow else "0",
            },
        )

        if save:
            self.save_config()

        return {
            "saved": save,
            "port_number": port_number,
            "summary": {
                "alias": resolved_alias[:32],
                "admin_enabled": resolved_admin,
                "speed_code": resolved_speed,
                "duplex_code": resolved_duplex,
                "flow_control_enabled": resolved_flow,
            },
        }

    def set_port_vlan_settings(
        self,
        port_number: int,
        *,
        pvid: int | None = None,
        frame_type_code: str | None = None,
        ingress_filtering_enabled: bool | None = None,
        vlan_trunk_enabled: bool | None = None,
        save: bool = True,
    ) -> dict:
        vlan = self._load_port_vlan_form(port_number)
        resolved_pvid = int(vlan["pvid"]) if pvid is None else int(pvid)
        resolved_frame_type = str(frame_type_code if frame_type_code is not None else vlan["frame_type_code"])
        resolved_ingress = bool(vlan["ingress_filtering_code"] == "1") if ingress_filtering_enabled is None else bool(ingress_filtering_enabled)
        resolved_trunk = bool(vlan["vlan_trunk_code"] == "1") if vlan_trunk_enabled is None else bool(vlan_trunk_enabled)

        self._request(
            "POST",
            data={
                "XSSID": vlan["xssid"],
                "portlist": vlan["portlist"],
                "cmd": 1292,
                "pvid": str(resolved_pvid),
                "frametype": resolved_frame_type,
                "vlan_igrfilter": "1" if resolved_ingress else "0",
                "vlan_trunk": "1" if resolved_trunk else "0",
            },
        )

        if save:
            self.save_config()

        return {
            "saved": save,
            "port_number": port_number,
            "summary": {
                "pvid": resolved_pvid,
                "frame_type_code": resolved_frame_type,
                "ingress_filtering_enabled": resolved_ingress,
                "vlan_trunk_enabled": resolved_trunk,
            },
        }

    def set_port_memberships(
        self,
        port_number: int,
        memberships: dict[int, str],
        *,
        save: bool = True,
    ) -> dict:
        if not memberships:
            return {"saved": False, "port_number": port_number, "summary": {"memberships": {}}}

        membership_index = max(port_number - 1, 0)
        first_page = self._load_vlan_membership_form()
        available_vlan_ids = {int(item["vlan_id"]) for item in first_page["vlan_options"]}
        pages: dict[int, dict] = {int(first_page["vid"]): first_page}
        applied_memberships: dict[int, str] = {}

        for vlan_id, membership_code in sorted(memberships.items()):
            if vlan_id not in available_vlan_ids:
                continue
            page = pages.get(vlan_id)
            if page is None:
                page = self._load_vlan_membership_form(vlan_id)
                pages[vlan_id] = page

            payload: dict[str, object] = {
                "XSSID": page["xssid"],
                "cmd": 1294,
                "vid": str(vlan_id),
            }
            for index, value in page["vlan_modes"].items():
                payload[f"vlanMode_{index}"] = value

            merged_memberships = dict(page["memberships"])
            merged_memberships[membership_index] = str(membership_code)
            for index, value in merged_memberships.items():
                payload[f"membership_{index}"] = value

            self._request("POST", data=payload)
            applied_memberships[int(vlan_id)] = str(membership_code)

        if save:
            self.save_config()

        return {
            "saved": save,
            "port_number": port_number,
            "summary": {
                "memberships": applied_memberships,
            },
        }

    def _load_port_physical_form(self, port_number: int) -> dict:
        response = self._request("POST", data={"cmd": 769, "port": str(port_number)})
        parsed = _parse_document(response.text)
        return {
            "xssid": _input_value(parsed.inputs, "XSSID"),
            "portlist": _input_value(parsed.inputs, "portlist", str(port_number)),
            "alias": _input_value(parsed.inputs, "descp"),
            "state_code": _checked_radio_value(parsed.inputs, "state", "1"),
            "speed_code": _checked_radio_value(parsed.inputs, "speed", "0"),
            "duplex_code": _checked_radio_value(parsed.inputs, "duplex", "0"),
            "flow_control_code": _checked_radio_value(parsed.inputs, "fc", "0"),
        }

    def _load_port_vlan_form(self, port_number: int) -> dict:
        response = self._request("POST", data={"cmd": 1291, "port": str(port_number)})
        parsed = _parse_document(response.text)
        pvid_raw = _input_value(parsed.inputs, "pvid", "1")
        return {
            "xssid": _input_value(parsed.inputs, "XSSID"),
            "portlist": _input_value(parsed.inputs, "portlist", str(port_number)),
            "pvid": int(pvid_raw) if pvid_raw.isdigit() else 1,
            "frame_type_code": _checked_radio_value(parsed.inputs, "frametype", "0"),
            "ingress_filtering_code": _checked_radio_value(parsed.inputs, "vlan_igrfilter", "0"),
            "vlan_trunk_code": _checked_radio_value(parsed.inputs, "vlan_trunk", "0"),
        }

    def _load_vlan_membership_form(self, vlan_id: int | None = None) -> dict:
        params: dict[str, object] = {"cmd": 1293}
        if vlan_id is not None:
            params["vid"] = str(vlan_id)
        response = self._request("GET", params=params)
        parsed = _parse_document(response.text)

        memberships: dict[int, str] = {}
        vlan_modes: dict[int, str] = {}
        for item in parsed.inputs:
            name = item.get("name", "")
            if name.startswith("membership_") and item.get("type") == "radio" and "checked" in item:
                try:
                    memberships[int(name.split("_", 1)[1])] = item.get("value", "0")
                except ValueError:
                    continue
            if name.startswith("vlanMode_"):
                try:
                    vlan_modes[int(name.split("_", 1)[1])] = item.get("value", "0")
                except ValueError:
                    continue

        select_data = parsed.selects.get("vid", {})
        options = select_data.get("options") or []
        assert isinstance(options, list)
        vlan_options: list[dict[str, object]] = []
        for option in options:
            if not isinstance(option, dict):
                continue
            attrs = option.get("attrs") or {}
            assert isinstance(attrs, dict)
            raw_value = str(attrs.get("value", "")).strip()
            if not raw_value.isdigit():
                continue
            vlan_options.append({
                "vlan_id": int(raw_value),
                "name": (str(option.get("text", "")).strip() or f"VLAN {raw_value}"),
            })

        current_vid_raw = _selected_option_value(parsed.selects, "vid")
        current_vid = int(current_vid_raw) if current_vid_raw.isdigit() else (vlan_options[0]["vlan_id"] if vlan_options else 1)
        return {
            "xssid": _input_value(parsed.inputs, "XSSID"),
            "vid": int(current_vid),
            "vlan_options": vlan_options,
            "memberships": memberships,
            "vlan_modes": vlan_modes,
        }

    def get_vlan_catalog(self) -> list[dict[str, object]]:
        page = self._load_vlan_membership_form()
        return page["vlan_options"]

    def get_port_settings(self, port_number: int) -> dict:
        physical = self._load_port_physical_form(port_number)
        vlan = self._load_port_vlan_form(port_number)
        return {
            "port_number": port_number,
            "alias": physical["alias"],
            "admin_enabled": physical["state_code"] == "1",
            "speed_code": physical["speed_code"],
            "speed_label": PORT_SPEED_LABELS.get(physical["speed_code"], "Auto"),
            "duplex_code": physical["duplex_code"],
            "duplex_label": PORT_DUPLEX_LABELS.get(physical["duplex_code"], "Auto"),
            "flow_control_code": physical["flow_control_code"],
            "flow_control_enabled": physical["flow_control_code"] == "1",
            "pvid": vlan["pvid"],
            "frame_type_code": vlan["frame_type_code"],
            "frame_type_label": FRAME_TYPE_LABELS.get(vlan["frame_type_code"], "All"),
            "ingress_filtering_code": vlan["ingress_filtering_code"],
            "ingress_filtering_enabled": vlan["ingress_filtering_code"] == "1",
            "vlan_trunk_code": vlan["vlan_trunk_code"],
            "vlan_trunk_enabled": vlan["vlan_trunk_code"] == "1",
        }

    def get_port_profile(self, port_number: int) -> dict:
        settings = self.get_port_settings(port_number)
        membership_index = max(port_number - 1, 0)
        initial_membership_page = self._load_vlan_membership_form()
        available_vlans = initial_membership_page["vlan_options"]

        memberships: dict[int, str] = {}
        first_vid = initial_membership_page["vid"]
        memberships[first_vid] = initial_membership_page["memberships"].get(membership_index, "0")
        for item in available_vlans:
            vlan_id = int(item["vlan_id"])
            if vlan_id == first_vid:
                continue
            page = self._load_vlan_membership_form(vlan_id)
            memberships[vlan_id] = page["memberships"].get(membership_index, "0")

        settings["memberships"] = memberships
        settings["available_vlans"] = available_vlans
        return settings

    def update_port(
        self,
        port_number: int,
        *,
        alias: str,
        admin_enabled: bool,
        speed_code: str,
        duplex_code: str,
        flow_control_enabled: bool,
        pvid: int,
        frame_type_code: str,
        ingress_filtering_enabled: bool,
        vlan_trunk_enabled: bool,
        memberships: dict[int, str],
        save: bool = True,
    ) -> dict:
        self.set_port_physical(
            port_number,
            alias=alias,
            admin_enabled=admin_enabled,
            speed_code=str(speed_code),
            duplex_code=str(duplex_code),
            flow_control_enabled=flow_control_enabled,
            save=False,
        )
        self.set_port_vlan_settings(
            port_number,
            pvid=int(pvid),
            frame_type_code=str(frame_type_code),
            ingress_filtering_enabled=ingress_filtering_enabled,
            vlan_trunk_enabled=vlan_trunk_enabled,
            save=False,
        )
        self.set_port_memberships(port_number, memberships, save=False)

        if save:
            self.save_config()

        return {
            "saved": save,
            "port_number": port_number,
            "summary": {
                "alias": alias[:32],
                "admin_enabled": admin_enabled,
                "speed_code": str(speed_code),
                "duplex_code": str(duplex_code),
                "flow_control_enabled": flow_control_enabled,
                "pvid": int(pvid),
                "frame_type_code": str(frame_type_code),
                "ingress_filtering_enabled": ingress_filtering_enabled,
                "vlan_trunk_enabled": vlan_trunk_enabled,
                "memberships": {int(key): str(value) for key, value in memberships.items()},
            },
        }

    def set_simple_port_membership(self, port_number: int, vlan_id: int, mode: str, *, save: bool = True) -> dict:
        current = self.get_port_profile(port_number)
        memberships = dict(current["memberships"])
        if vlan_id not in memberships:
            memberships[vlan_id] = "0"

        if mode == "tagged":
            memberships[vlan_id] = "2"
            pvid = int(current["pvid"])
        elif mode == "excluded":
            memberships[vlan_id] = "0"
            pvid = int(current["pvid"])
        else:
            for existing_vlan_id, code in list(memberships.items()):
                if code == "3" and existing_vlan_id != vlan_id:
                    memberships[existing_vlan_id] = "0"
            memberships[vlan_id] = "3"
            pvid = int(vlan_id)

        return self.update_port(
            port_number,
            alias=str(current["alias"]),
            admin_enabled=bool(current["admin_enabled"]),
            speed_code=str(current["speed_code"]),
            duplex_code=str(current["duplex_code"]),
            flow_control_enabled=bool(current["flow_control_enabled"]),
            pvid=pvid,
            frame_type_code=str(current["frame_type_code"]),
            ingress_filtering_enabled=bool(current["ingress_filtering_enabled"]),
            vlan_trunk_enabled=bool(current["vlan_trunk_enabled"]),
            memberships=memberships,
            save=save,
        )

    def create_vlan(self, vlan_id: int, name: str, *, save: bool = True) -> dict:
        open_form = self._request("POST", data={"cmd": 1284})
        parsed = _parse_document(open_form.text)
        xssid = _input_value(parsed.inputs, "XSSID")
        self._request(
            "POST",
            data={
                "XSSID": xssid,
                "cmd": 1285,
                "vlanlist": str(vlan_id),
                "vlanAction": "0",
                "name": name[:28],
            },
        )
        if save:
            self.save_config()
        return {"saved": save, "vlan_id": vlan_id, "name": name[:28]}

    def update_vlan(self, current_vlan_id: int, vlan_id: int, name: str, *, save: bool = True) -> dict:
        form = self._request("GET", params={"cmd": 1286, "_edit": str(current_vlan_id)})
        parsed = _parse_document(form.text)
        xssid = _input_value(parsed.inputs, "XSSID")
        self._request(
            "POST",
            data={
                "XSSID": xssid,
                "cmd": 1287,
                "vidValue": str(vlan_id),
                "editName": name[:32],
            },
        )
        if save:
            self.save_config()
        return {"saved": save, "previous_vlan_id": current_vlan_id, "vlan_id": vlan_id, "name": name[:32]}

    def delete_vlan(self, vlan_id: int, *, save: bool = True) -> dict:
        self._request("GET", params={"cmd": 1289, "_del": str(vlan_id)})
        if save:
            self.save_config()
        return {"saved": save, "vlan_id": vlan_id}
