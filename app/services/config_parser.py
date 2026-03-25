
def parse_system_output(raw: str) -> dict:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    return {"lines": lines, "raw": raw}
