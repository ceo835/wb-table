#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SELF_RELATIVE_PATH = Path("scripts/check_no_secrets.py")
SKIP_NAMES = {
    ".env",
    "credentials.json",
}
SKIP_PARTS = {
    "__pycache__",
    ".git",
    "data/raw",
    "_api_audit_raw",
}
TEXT_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".csv",
    ".json",
    ".yml",
    ".yaml",
    ".ini",
    ".toml",
    ".env.example",
}
ENV_PATTERNS = {
    "WB_TOKEN": re.compile(r"(?m)^(?!\s*#)[ \t]*(?:export[ \t]+)?WB_TOKEN[ \t]*=[ \t]*(?P<value>[^\n\r]*)$"),
    "WB_ANALYTICS_TOKEN": re.compile(
        r"(?m)^(?!\s*#)[ \t]*(?:export[ \t]+)?WB_ANALYTICS_TOKEN[ \t]*=[ \t]*(?P<value>[^\n\r]*)$"
    ),
    "MPSTATS_API_TOKEN": re.compile(
        r"(?m)^(?!\s*#)[ \t]*(?:export[ \t]+)?MPSTATS_API_TOKEN[ \t]*=[ \t]*(?P<value>[^\n\r]*)$"
    ),
    "GOOGLE_APPLICATION_CREDENTIALS": re.compile(
        r"(?m)^(?!\s*#)[ \t]*(?:export[ \t]+)?GOOGLE_APPLICATION_CREDENTIALS[ \t]*=[ \t]*(?P<value>[^\n\r]*)$"
    ),
}
PRIVATE_KEY_JSON_PATTERN = re.compile(r'"private_key"\s*:\s*"(?P<value>.+?)"')
PLACEHOLDER_MARKERS = (
    "your_",
    "example",
    "changeme",
    "replace",
    "placeholder",
    "token_here",
    "<",
)
RUNTIME_REFERENCE_MARKERS = (
    "get_env_variable(",
    "os.getenv(",
    "environ.get(",
    "env(",
)


def should_scan(path: Path, root_dir: Path = ROOT_DIR) -> bool:
    if path.name in SKIP_NAMES:
        return False
    if path.relative_to(root_dir) == SELF_RELATIVE_PATH:
        return False
    normalized = path.as_posix()
    if any(part in normalized for part in SKIP_PARTS):
        return False
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name.endswith(".env.example")


def normalize_value(value: str) -> str:
    return value.strip().strip('"').strip("'")


def is_placeholder_value(value: str) -> bool:
    normalized = normalize_value(value)
    lowered = normalized.lower()
    if not normalized:
        return True
    if normalized in {"credentials.json", "your_google_sheet_id"}:
        return True
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def is_runtime_reference(value: str) -> bool:
    normalized = normalize_value(value)
    if normalized in {"(", ")"}:
        return True
    return any(marker in normalized for marker in RUNTIME_REFERENCE_MARKERS)


def find_violations(root_dir: Path = ROOT_DIR) -> list[str]:
    violations: list[str] = []
    for path in root_dir.rglob("*"):
        if not path.is_file() or not should_scan(path, root_dir=root_dir):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        relative_path = path.relative_to(root_dir)

        for env_name, pattern in ENV_PATTERNS.items():
            for match in pattern.finditer(content):
                value = match.group("value")
                if is_placeholder_value(value) or is_runtime_reference(value):
                    continue
                violations.append(f"{relative_path}: matched {env_name}")
                break

        if PRIVATE_KEY_JSON_PATTERN.search(content):
            violations.append(f'{relative_path}: matched "private_key"')
            continue

        for line in content.splitlines():
            if line.strip() == "-----BEGIN PRIVATE KEY-----":
                violations.append(f"{relative_path}: matched PEM private key header")
                break

    return violations


def main() -> int:
    violations = find_violations()
    if violations:
        print("Secret check failed:")
        for violation in violations:
            print(f"- {violation}")
        return 1

    print("No secrets detected in scanned project files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
