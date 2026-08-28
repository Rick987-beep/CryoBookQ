"""Hub smoke + deploy dry-run."""

import subprocess
from pathlib import Path


def test_deploy_dry_run() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "deploy" / "deploy.sh"
    assert script.is_file()
    proc = subprocess.run(
        ["bash", str(script), "--dry-run"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "dry_run=1" in proc.stdout
    assert "BOOKQ_ALLOW_DEPLOY=1" in proc.stdout
