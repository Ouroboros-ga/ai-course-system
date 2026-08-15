"""Regression coverage for isolated LibreOffice conversion profiles."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.common import slide_converter


def test_office_conversions_use_distinct_libreoffice_profiles(tmp_path, monkeypatch):
    """Concurrent-capable conversions must not share LibreOffice state."""
    first_source = tmp_path / "first.pptx"
    second_source = tmp_path / "second.pptx"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")
    captured_profiles: list[str] = []

    monkeypatch.setattr(slide_converter, "_find_libreoffice", lambda: "/usr/bin/libreoffice")

    def fake_run(command, **_kwargs):
        profile_arg = next(arg for arg in command if arg.startswith("-env:UserInstallation="))
        captured_profiles.append(profile_arg)
        output_dir = Path(command[command.index("--outdir") + 1])
        input_path = Path(command[-1])
        (output_dir / f"{input_path.stem}.pdf").write_bytes(b"%PDF-fake")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(slide_converter.subprocess, "run", fake_run)

    assert slide_converter.convert_office_to_pdf(str(first_source), str(tmp_path)) == str(tmp_path / "first.pdf")
    assert slide_converter.convert_office_to_pdf(str(second_source), str(tmp_path)) == str(tmp_path / "second.pdf")

    assert len(captured_profiles) == 2
    assert captured_profiles[0] != captured_profiles[1]
    assert all(profile.startswith("-env:UserInstallation=file:") for profile in captured_profiles)
