"""Static checks for the DevOps artefacts (scripts + systemd units).

Exercised as pytest tests so regressions (broken bash syntax, malformed
systemd directives) surface in CI without needing a real VPS.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
SYSTEMD = REPO_ROOT / "systemd"


class TestScriptsExistExecutable:
    @pytest.mark.parametrize("name", ["provision_vps.sh", "backup.sh"])
    def test_script_is_present_and_executable(self, name: str) -> None:
        path = SCRIPTS / name
        assert path.is_file(), f"{path} missing"
        # Any executable bit set is sufficient.
        assert path.stat().st_mode & 0o111, f"{path} not executable"

    @pytest.mark.parametrize("name", ["provision_vps.sh", "backup.sh"])
    def test_script_has_bash_shebang(self, name: str) -> None:
        path = SCRIPTS / name
        first_line = path.read_text().splitlines()[0]
        assert first_line.startswith("#!") and "bash" in first_line

    @pytest.mark.parametrize("name", ["provision_vps.sh", "backup.sh"])
    def test_bash_syntax_valid(self, name: str) -> None:
        """`bash -n` catches syntax errors without executing the script."""
        result = subprocess.run(  # noqa: S603
            ["bash", "-n", str(SCRIPTS / name)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize(
        "name, strictness",
        [
            ("provision_vps.sh", "set -euo pipefail"),
            ("backup.sh", "set -euo pipefail"),
        ],
    )
    def test_script_uses_strict_mode(self, name: str, strictness: str) -> None:
        content = (SCRIPTS / name).read_text()
        assert strictness in content


class TestProvisionIdempotence:
    def test_uses_detection_primitives(self) -> None:
        """Idempotence requires checking state before acting. The script
        must use `command -v`, `dpkg -s`, or `systemctl is-active` before
        install/start commands."""
        content = (SCRIPTS / "provision_vps.sh").read_text()
        assert "command -v" in content
        assert "dpkg -s" in content
        assert "systemctl is-active" in content


class TestBackupGates:
    def test_rclone_sync_is_gated_on_remote(self) -> None:
        content = (SCRIPTS / "backup.sh").read_text()
        assert "rclone listremotes" in content
        # The actual guard must reference the `backup:` remote name.
        assert "backup:" in content

    def test_retention_prunes_daily_over_30_days(self) -> None:
        content = (SCRIPTS / "backup.sh").read_text()
        assert "-mtime +30" in content

    def test_sqlite_uses_backup_command(self) -> None:
        """`.backup` is atomic under concurrent writes; plain cp is not."""
        content = (SCRIPTS / "backup.sh").read_text()
        assert ".backup" in content and "sqlite3" in content


class TestSystemdUnits:
    UNITS = ("pte-streamlit.service", "pte-backup.service", "pte-backup.timer")

    @pytest.mark.parametrize("name", UNITS)
    def test_unit_file_exists(self, name: str) -> None:
        assert (SYSTEMD / name).is_file()

    @pytest.mark.parametrize("name", UNITS)
    def test_unit_has_install_section(self, name: str) -> None:
        content = (SYSTEMD / name).read_text()
        assert "[Install]" in content

    def test_streamlit_service_uses_portfolio_user(self) -> None:
        content = (SYSTEMD / "pte-streamlit.service").read_text()
        assert "User=portfolio" in content
        assert "WorkingDirectory=/home/portfolio/workspace/portfolio-thesis-engine" in content
        assert "EnvironmentFile=" in content

    def test_streamlit_service_restart_on_failure(self) -> None:
        content = (SYSTEMD / "pte-streamlit.service").read_text()
        assert "Restart=on-failure" in content
        assert "RestartSec=" in content

    def test_backup_timer_persistent(self) -> None:
        content = (SYSTEMD / "pte-backup.timer").read_text()
        assert "Persistent=true" in content

    def test_backup_timer_points_at_backup_service(self) -> None:
        content = (SYSTEMD / "pte-backup.timer").read_text()
        assert "Unit=pte-backup.service" in content

    @pytest.mark.skipif(
        shutil.which("systemd-analyze") is None,
        reason="systemd-analyze not installed",
    )
    def test_systemd_analyze_verify(self) -> None:
        """`systemd-analyze verify` parses each unit and reports errors."""
        result = subprocess.run(  # noqa: S603
            [
                "systemd-analyze",
                "verify",
                str(SYSTEMD / "pte-streamlit.service"),
                str(SYSTEMD / "pte-backup.service"),
                str(SYSTEMD / "pte-backup.timer"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"systemd-analyze exited {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
