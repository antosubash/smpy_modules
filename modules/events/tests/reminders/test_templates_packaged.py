"""The reminder templates ship in the wheel and render from an installed copy, not the checkout.

The wheel is built, unpacked and put first on ``sys.path`` of a fresh interpreter, so what runs is
the packaged ``sm_events`` and its templates, found through the package loader (never a path
relative to a source tree)."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2]
PROBE = """
import sm_events, sys
from pathlib import Path
from sm_events.reminders import message

root = Path(sys.argv[1]).resolve()
assert Path(sm_events.__file__).resolve().is_relative_to(root), sm_events.__file__
env = message.environment()
values = dict(intro="I", title="<b>T</b>", when_line="W", place_lines=["P"], moved_line="",
              open_label="O", manage_label="M", event_url="http://x/e", manage_url="http://x/m",
              footer="F", lang="en", details="D")
text = env.get_template("reminder.txt").render(**values)
html = env.get_template("reminder.html").render(**values)
assert "<b>T</b>" not in html and "&lt;b&gt;" in html   # html is escaped
assert "http://x/e" in text and "&" not in text         # text is not
print("ok")
"""


@pytest.mark.timeout(300)
def test_templates_render_from_the_built_wheel(tmp_path: Path) -> None:
    out = tmp_path / "wheel"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out), "-q", str(MODULE)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(out.glob("simple_module_events-*.whl"))
    unpacked = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as z:
        names = z.namelist()
        z.extractall(unpacked)
    assert "sm_events/reminders/templates/reminder.html" in names
    assert "sm_events/reminders/templates/reminder.txt" in names
    run = subprocess.run(
        [sys.executable, "-c", PROBE, str(unpacked)],
        cwd=tmp_path,
        env={"PYTHONPATH": str(unpacked), "PATH": "/usr/bin"},
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr[-800:]
    assert run.stdout.strip() == "ok"
