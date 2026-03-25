from __future__ import annotations

from abc import ABC, abstractmethod


class SwitchDriver(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def get_system_info(self) -> dict: ...

    @abstractmethod
    def get_interfaces(self) -> list[dict]: ...

    @abstractmethod
    def get_vlans(self) -> list[dict]: ...

    @abstractmethod
    def create_vlan(self, vlan_id: int, name: str, dry_run: bool = True) -> dict: ...

    @abstractmethod
    def delete_vlan(self, vlan_id: int, dry_run: bool = True) -> dict: ...

    @abstractmethod
    def assign_port_to_vlan(self, port: int, vlan_id: int, mode: str, dry_run: bool = True) -> dict: ...

    @abstractmethod
    def set_port_admin_state(self, port: int, enabled: bool, dry_run: bool = True) -> dict: ...

    @abstractmethod
    def set_poe_state(self, port: int, enabled: bool, dry_run: bool = True) -> dict: ...

    @abstractmethod
    def reboot_device(self, dry_run: bool = True) -> dict: ...

    @abstractmethod
    def backup_config(self, dry_run: bool = True) -> dict: ...

    @abstractmethod
    def save_config(self, dry_run: bool = True) -> dict: ...
