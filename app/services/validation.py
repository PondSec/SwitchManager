from ipaddress import ip_address


class ValidationError(ValueError):
    pass


def validate_host(host: str) -> str:
    try:
        ip_address(host)
    except ValueError as exc:
        raise ValidationError("Ungültige Management-IP") from exc
    return host


def validate_port_list(raw_ports: str) -> list[int]:
    ports = []
    for part in raw_ports.split(","):
        value = int(part.strip())
        if value < 1 or value > 48:
            raise ValidationError("Portnummer außerhalb des gültigen Bereichs (1-48)")
        ports.append(value)
    return sorted(set(ports))
