import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPTS = [
    "deploy/install.sh",
    "deploy/htm-menu.sh",
    "deploy/discover.sh",
    "deploy/install-decklink.sh",
    "deploy/console-routing.sh",
]


def test_deploy_scripts_are_valid_bash():
    script_paths = [str(REPO_ROOT / script) for script in DEPLOY_SCRIPTS]

    result = subprocess.run(
        ["bash", "-n", *script_paths],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_deploy_scripts_do_not_contain_conflict_markers():
    markers = ("<<<<<<<", "=======", ">>>>>>>")

    for script in DEPLOY_SCRIPTS:
        contents = (REPO_ROOT / script).read_text()
        assert not any(marker in contents for marker in markers), script
