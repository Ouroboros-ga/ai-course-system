from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "deploy" / "scripts" / "configure-server-runtime.sh"


def _parse_env(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )


def _bash_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    return "/mnt/{}/{}".format(path.drive.rstrip(":").lower(), "/".join(path.parts[1:]))


def _run_initializer(app_root: Path, *, mode: str | None = None) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    script_preamble = f"export SMARTCARB_APP_ROOT={shlex.quote(_bash_path(app_root))}\n"
    bootstrap_mode = mode or "preserve"
    script_preamble += f"export SMARTCARB_JUDGE0_BOOTSTRAP_MODE={shlex.quote(bootstrap_mode)}\n"
    return subprocess.run(
        [shutil.which("bash") or "bash", "-s"],
        check=False,
        capture_output=True,
        env=environment,
        input=script_preamble.encode("utf-8") + SCRIPT.read_bytes().replace(b"\r\n", b"\n"),
    )


def test_runtime_initializer_preserves_existing_remote_judge0_config(tmp_path: Path):
    backend_root = tmp_path / "backend"
    backend_root.mkdir()
    (backend_root / ".env").write_text(
        "JUDGE0_API_URL=http://192.0.2.24:2358\n"
        "JUDGE0_AUTHN_HEADER=X-Remote-Authn\n"
        "JUDGE0_AUTHN_TOKEN=remote-authn\n"
        "JUDGE0_AUTHZ_HEADER=X-Remote-Authz\n"
        "JUDGE0_AUTHZ_TOKEN=remote-authz\n"
        "JUDGE0_ENABLED=true\n",
        encoding="utf-8",
    )

    before = _parse_env(backend_root / ".env")
    result = _run_initializer(tmp_path)

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    backend_env = _parse_env(backend_root / ".env")
    assert {
        key: value for key, value in backend_env.items() if key.startswith("JUDGE0_")
    } == {key: value for key, value in before.items() if key.startswith("JUDGE0_")}
    assert not (tmp_path / "deploy" / "judge0" / ".env").exists()


def test_runtime_initializer_configures_local_judge0_only_when_requested(tmp_path: Path):
    backend_root = tmp_path / "backend"
    backend_root.mkdir()
    (backend_root / ".env").write_text("", encoding="utf-8")

    result = _run_initializer(tmp_path, mode="local")

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    backend_env = _parse_env(backend_root / ".env")
    local_judge0_env = _parse_env(tmp_path / "deploy" / "judge0" / ".env")
    assert backend_env["JUDGE0_API_URL"] == "http://127.0.0.1:2358"
    assert backend_env["JUDGE0_AUTHN_HEADER"] == "X-Auth-Token"
    assert backend_env["JUDGE0_AUTHZ_HEADER"] == "X-Auth-User"
    assert backend_env["JUDGE0_ENABLED"] == "false"
    assert backend_env["JUDGE0_AUTHN_TOKEN"] == local_judge0_env["JUDGE0_AUTHN_TOKEN"]
    assert backend_env["JUDGE0_AUTHZ_TOKEN"] == local_judge0_env["JUDGE0_AUTHZ_TOKEN"]
    if os.name != "nt":
        assert stat.S_IMODE((backend_root / ".env").stat().st_mode) == 0o600
        assert stat.S_IMODE((tmp_path / "deploy" / "judge0" / ".env").stat().st_mode) == 0o600
