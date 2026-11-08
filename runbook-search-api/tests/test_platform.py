"""Platform contract tests: container packaging and Helm image policy."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "helm" / "mlops-search"
DIGEST = "sha256:" + "a" * 64

helm = shutil.which("helm")
needs_helm = pytest.mark.skipif(helm is None, reason="helm binary is not installed")


def render(*sets: str) -> subprocess.CompletedProcess:
    args = [helm, "template", "blokhina-search-staging", str(CHART), "-n", "mlops-students"]
    for item in sets:
        args += ["--set", item]
    return subprocess.run(args, capture_output=True, text=True)


def test_dockerfile_ships_verified_artifacts() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "COPY --from=builder /build/artifacts" in dockerfile
    assert "USER 10001" in dockerfile


@needs_helm
def test_chart_renders_immutable_digest() -> None:
    result = render(f"image.digest={DIGEST}", "image.repository=docker.io/valeblok/runbook-search-api")
    assert result.returncode == 0, result.stderr
    manifest = result.stdout
    assert f'image: "docker.io/valeblok/runbook-search-api@{DIGEST}"' in manifest
    assert ":latest" not in manifest
    assert f'IMAGE_DIGEST: "{DIGEST}"' in manifest
    assert "type: ClusterIP" in manifest
    for required in ("readinessProbe", "livenessProbe", "readOnlyRootFilesystem: true",
                     "runAsNonRoot: true", "limits:", "helm.sh/hook\": test"):
        assert required in manifest, required


@needs_helm
@pytest.mark.parametrize("sets", [
    [],
    ["image.digest="],
    ["image.digest=latest"],
    ["image.digest=sha256:abc"],
    [f"image.digest={DIGEST}", "image.repository=docker.io/valeblok/runbook-search-api:latest"],
    [f"image.digest={DIGEST}", "image.tag=latest"],
    [f"image.digest={DIGEST}", "rankingMode=bogus"],
])
def test_chart_rejects_mutable_or_invalid_image(sets: list[str]) -> None:
    result = render(*sets)
    assert result.returncode != 0, result.stdout
