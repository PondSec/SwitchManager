from __future__ import annotations

import socket

import paramiko
from flask import current_app


class SSHExecutionError(RuntimeError):
    pass


class SSHClientService:
    def __init__(self, host: str, port: int, username: str, password: str | None = None, key_path: str | None = None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_path = key_path
        self.client: paramiko.SSHClient | None = None

    def connect(self) -> None:
        self.client = paramiko.SSHClient()
        policy = current_app.config.get("SSH_HOST_KEY_POLICY", "reject")
        if policy == "auto-add":
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        elif policy == "warning":
            self.client.set_missing_host_key_policy(paramiko.WarningPolicy())
        else:
            self.client.set_missing_host_key_policy(paramiko.RejectPolicy())

        try:
            self.client.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                key_filename=self.key_path,
                timeout=current_app.config.get("SSH_CONNECT_TIMEOUT", 8),
                look_for_keys=False,
            )
        except (paramiko.SSHException, socket.error) as exc:
            raise SSHExecutionError(f"SSH-Verbindung fehlgeschlagen: {exc}") from exc

    def execute_command(self, command: str) -> str:
        if not self.client:
            raise SSHExecutionError("SSH-Client nicht verbunden")
        stdin, stdout, stderr = self.client.exec_command(command, timeout=current_app.config.get("SSH_DEFAULT_TIMEOUT", 8))
        output = stdout.read().decode("utf-8", errors="replace")
        error = stderr.read().decode("utf-8", errors="replace")
        if error.strip():
            raise SSHExecutionError(error.strip())
        return output.strip()

    def execute_config_commands(self, commands: list[str]) -> list[str]:
        results = []
        for cmd in commands:
            results.append(self.execute_command(cmd))
        return results

    def close(self) -> None:
        if self.client:
            self.client.close()
            self.client = None
