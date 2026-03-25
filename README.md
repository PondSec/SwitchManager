# SwitchManager

Professionelle, mehrseitige Flask-Webanwendung für self-hosted Switch-Management mit Dark-Mode-UI, Audit-Trail und vorbereitetem Device-Abstraction-Layer.

## Features
- Flask + Blueprint-Architektur
- SQLAlchemy + SQLite
- Login, Rollen (`admin`, `operator`, `readonly`)
- SSH-Layer (Paramiko) als primärer Transport
- Vorbereitung für weitere Transporte (Telnet/SNMP/HTTP Replay)
- VLAN/Port/PoE/System-Aktionen mit Dry-Run-Vorschau
- Erweiterte Netzwerk-Profile (DHCP, DNS, IGMP, Guarding, mDNS, UPnP) mit komplexer Admin-UI und Apply/Dry-Run
- Audit-Logging in DB + Log-Datei
- Dashboard, Geräte, VLAN, Ports (inkl. 24-Port Frontpanel), PoE, System, Audit, Einstellungen
- Health-Endpoint `/health/`

## Projektstruktur
```text
app/
  blueprints/
  forms/
  models/
  services/
  static/
  templates/
  utils/
config.py
run.py
requirements.txt
.env.example
start.sh
```

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```
Standardmäßig startet die App auf `http://127.0.0.1:8237` (überschreibbar via `PORT`).

Alternativ:
```bash
./start.sh
```

## Login (Seed)
- Benutzer: `admin`
- Passwort: `admin12345`

> Passwort nach erstem Login ändern.

## SSH/Driver-Hinweise
Der `ZyxelSSHDriver` ist bewusst generisch und sicher kapsuliert. Unklare CLI-Befehle sind mit `TODO` markiert. Vor Produktion sind die modell-spezifischen Kommandos für die Zielhardware zwingend zu validieren.

## Sicherheit
- CSRF aktiviert
- serverseitige Validierung
- keine freie CLI-Eingabe im UI
- interne Action-zu-Command-Mappings via `CommandBuilder`

## Logging
- Datei: `logs/switchmanager.log`
- Audit: Tabelle `audit_log`
