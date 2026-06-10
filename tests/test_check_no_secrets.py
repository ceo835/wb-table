import shutil
import uuid
from pathlib import Path

from scripts.check_no_secrets import find_violations


WORKSPACE_TMP_ROOT = Path(__file__).resolve().parent / "_tmp_check_no_secrets"


def make_workspace_tmp_dir() -> Path:
    WORKSPACE_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = WORKSPACE_TMP_ROOT / uuid.uuid4().hex
    temp_dir.mkdir()
    return temp_dir


def cleanup_workspace_tmp_dirs() -> None:
    if WORKSPACE_TMP_ROOT.exists():
        shutil.rmtree(WORKSPACE_TMP_ROOT)


def test_ignores_placeholder_and_runtime_reference_values() -> None:
    temp_dir = make_workspace_tmp_dir()
    try:
        (temp_dir / "README.md").write_text(
            "\n".join(
                [
                    "WB_TOKEN=your_wb_token",
                    "WB_ANALYTICS_TOKEN=your_wb_analytics_token",
                    "MPSTATS_API_TOKEN=your_mpstats_token",
                    "GOOGLE_APPLICATION_CREDENTIALS=credentials.json",
                ]
            ),
            encoding="utf-8",
        )
        (temp_dir / "settings.py").write_text(
            'WB_TOKEN = get_env_variable("WB_TOKEN", required=False)\n',
            encoding="utf-8",
        )

        assert find_violations(temp_dir) == []
    finally:
        cleanup_workspace_tmp_dirs()


def test_detects_literal_secret_assignment() -> None:
    temp_dir = make_workspace_tmp_dir()
    try:
        (temp_dir / "leak.txt").write_text("WB_TOKEN=super_secret_prod_token\n", encoding="utf-8")

        violations = find_violations(temp_dir)

        assert violations == ["leak.txt: matched WB_TOKEN"]
    finally:
        cleanup_workspace_tmp_dirs()


def test_detects_pem_private_key_header() -> None:
    temp_dir = make_workspace_tmp_dir()
    try:
        (temp_dir / "key.txt").write_text("-----BEGIN PRIVATE KEY-----\n", encoding="utf-8")

        violations = find_violations(temp_dir)

        assert violations == ["key.txt: matched PEM private key header"]
    finally:
        cleanup_workspace_tmp_dirs()
