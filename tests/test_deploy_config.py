"""The deployment pipeline's configuration: the deploy script, the SSM document, the CI deploy job, image pinning."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
SCRIPT = ROOT / "deploy" / "deploy.sh"
DOC = json.loads((ROOT / "deploy" / "ssm-document.json").read_text(encoding="utf-8"))


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason="needs a real bash (Linux/macOS)")
def test_deploy_script_is_valid_bash():
    bash = shutil.which("bash")
    result = subprocess.run([bash, "-n", str(SCRIPT)], capture_output=True, text=True)  # noqa: S603 (fixed arguments)
    assert result.returncode == 0, result.stderr


def test_deploy_script_is_strict_and_rolls_back():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert r"^[0-9a-f]{40}$" in text  # refuses anything but a full git SHA
    # migrate first, then roll out, then verify; a failed rollout or smoke test triggers the rollback function
    order = [text.index(marker) for marker in ("lumieree-migrate", "kubectl apply -k", "smoke /readyz", "DEPLOY_OK")]
    assert order == sorted(order)
    assert "rollout undo" in text and text.count("|| rollback") >= 3
    assert "not available in the registry" in text  # aborts early if CI did not publish the image


def test_ssm_document_accepts_only_a_git_sha():
    assert set(DOC["parameters"]) == {"tag"}
    pattern = DOC["parameters"]["tag"]["allowedPattern"]
    assert re.fullmatch(pattern, "a" * 40)
    for bad in ("", "main", "a" * 39, "a" * 41, "A" * 40, "x; rm -rf /", "a" * 40 + "\n; id"):
        assert not re.fullmatch(pattern, bad), bad
    commands = " ".join(DOC["mainSteps"][0]["inputs"]["runCommand"])
    assert commands.count("{{ tag }}") == 2  # checkout target and script argument: nothing else is templated
    assert "deploy/deploy.sh" in commands
    # SSM runs these lines with the system sh (dash on Ubuntu), which has no `set -o pipefail`; bash runs the script.
    assert "pipefail" not in commands and "set -eu" in commands


def test_ci_deploy_job_is_gated_keyless_and_serialised():
    job = CI[CI.index("\n  deploy:") :]
    assert "needs: [test, trivy-fs, image]" in job
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in job
    assert "id-token: write" in job
    assert "cancel-in-progress: false" in job
    assert "role-to-assume: arn:aws:iam::" in job
    assert "lumieree-deploy" in job and "tag=${GITHUB_SHA}" in job
    assert "secrets.AWS" not in CI and "AWS_SECRET_ACCESS_KEY" not in CI  # no long-lived keys
    # id-token is requested only by the deploy job, never workflow-wide
    assert CI.count("id-token: write") == 1


def test_overlays_override_the_full_image_name():
    """The base renames `lumieree` to the full name first; an overlay entry for `lumieree` silently does nothing."""
    for overlay in ("aws-k3s", "production"):
        text = (ROOT / "k8s" / "overlays" / overlay / "kustomization.yaml").read_text(encoding="utf-8")
        images = text[text.index("\nimages:") :].split("\npatches:")[0]
        assert re.search(r"-\s+name:\s+ghcr\.io/ryan-wong123/lumieree\s*$", images, flags=re.M), overlay
        assert not re.search(r"-\s+name:\s+lumieree\s*$", images, flags=re.M), overlay
