"""Deployment contract (Vercel): entrypoint, light dependencies, no heavy import, bundle hygiene.

``BIRD_TEST_CLEAN_VENV=1`` additionally builds a fresh virtual environment with uv, installs requirements.txt
only, and runs the same smoke test there (needs network access to the package index; about a minute).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEAVY = {"transformers", "torch", "datasets", "tokenizers", "huggingface_hub", "huggingface-hub", "peft", "accelerate"}


def names(requirements: list[str]) -> set[str]:
    return {
        re.split(r"[<>=!~ \[;]", r.strip(), maxsplit=1)[0].lower().replace("_", "-") for r in requirements if r.strip()
    }


def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_core_dependencies_are_light_and_mirrored_in_requirements_txt():
    project = pyproject()["project"]
    core = names(project["dependencies"])
    lines = [ln for ln in (ROOT / "requirements.txt").read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    assert core == names(lines), "requirements.txt must mirror [project].dependencies (Vercel installs the latter)"
    assert not core & HEAVY, core & HEAVY
    assert {"fastapi", "httpx", "jinja2", "jsonschema"} <= core
    extras = project["optional-dependencies"]
    assert {"transformers", "datasets"} <= names(extras["data"]) and "torch" in names(extras["train"])


def test_every_core_dependency_is_really_imported_by_the_app():
    """No dead weight in the function: each core package is imported somewhere under birds/ (lazily or not)."""
    module_of = {"python-pptx": "pptx", "python-docx": "docx", "jinja2": "jinja2", "pypdf": "pypdf", "pillow": "PIL"}
    source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "birds").rglob("*.py"))
    for package in names(pyproject()["project"]["dependencies"]):
        module = module_of.get(package, package.replace("-", "_"))
        assert re.search(rf"^\s*(?:import|from) {module}\b|_need\(\"{module}\"", source, re.M), package


def test_vercel_entrypoint_and_config():
    cfg = pyproject()["tool"]["vercel"]
    assert cfg["entrypoint"] == "app:app" and (ROOT / "app.py").is_file()
    vercel = json.loads((ROOT / "vercel.json").read_text())
    fn = vercel["functions"]["app.py"]
    from birds.web.settings import Settings

    assert 60 <= fn["maxDuration"] <= 300  # 300 s is the Hobby maximum
    assert Settings().max_seconds < fn["maxDuration"]  # the agent's budget ends before the function is killed
    for folder in ("tests", "docs", "scripts", "jobs", "out"):
        assert f"{folder}/**" in fn["excludeFiles"]
    ignore = (ROOT / ".vercelignore").read_text().splitlines()
    assert ignore[[i for i, ln in enumerate(ignore) if ln and not ln.startswith("#")][0]] == "/*"  # allowlist form
    assert {"!app.py", "!birds", "!pyproject.toml", "!vercel.json"} <= set(ignore)
    assert not any(
        ln.startswith("!") and ln[1:].split("/")[0] in ("tests", "out", "docs", "scripts", "jobs") for ln in ignore
    )


def test_only_one_fastapi_entrypoint_candidate_is_uploaded():
    """Vercel scans for `app = FastAPI(...)`; with the allowlist, tests/ is never uploaded, so only app.py matches."""
    assert re.search(r"^app = ", (ROOT / "app.py").read_text(), re.M)
    assert not (ROOT / "main.py").exists() and not (ROOT / "index.py").exists() and not (ROOT / "server.py").exists()
    assert not (ROOT / "api").exists(), "an api/ folder would create separate file-based functions"


def run_smoke(python: str, env: dict | None = None) -> dict:
    result = subprocess.run(
        [python, str(ROOT / "scripts" / "deploy_smoke.py")],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
        cwd=ROOT,
    )
    assert result.returncode == 0, (result.stdout[-800:], result.stderr[-1500:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_entrypoint_works_with_heavy_packages_blocked():
    report = run_smoke(sys.executable)
    assert report["ok"] and report["heavy_loaded"] == [] and all(report["checks"].values()), report
    assert report["import_seconds"] < 10


@pytest.mark.skipif(
    os.environ.get("BIRD_TEST_CLEAN_VENV") != "1", reason="set BIRD_TEST_CLEAN_VENV=1 (needs uv and the package index)"
)
def test_entrypoint_in_a_fresh_venv_with_only_requirements_txt(tmp_path):
    uv = shutil.which("uv")
    assert uv, "uv is required for this test"
    venv = tmp_path / "venv"
    subprocess.run(
        [uv, "venv", "--python", f"{sys.version_info.major}.{sys.version_info.minor}", str(venv)],
        check=True,
        capture_output=True,
    )
    python = str(venv / "bin" / "python")
    subprocess.run(
        [uv, "pip", "install", "--python", python, "-r", str(ROOT / "requirements.txt")],
        check=True,
        capture_output=True,
        timeout=600,
    )
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    report = run_smoke(python, env)
    site = next((venv / "lib").glob("python*/site-packages"))
    size = sum(p.stat().st_size for p in site.rglob("*") if p.is_file())
    installed = {p.name.split("-")[0].lower().replace("_", "-") for p in site.glob("*.dist-info")}
    print(json.dumps({"site_packages_mb": round(size / 1e6, 1), "packages": len(installed), **report}))
    assert report["ok"] and not installed & HEAVY and size < 250_000_000  # Vercel's Python limit is 500 MB
def _excluded(pattern: str):
    """The paths of the repository matched by a Vercel excludeFiles glob ('{a/**,b/**,**/*.png}')."""
    body = pattern.strip()
    globs = body[1:-1].split(",") if body.startswith("{") else [body]
    out = set()
    for g in globs:
        out |= {p.relative_to(ROOT).as_posix() for p in ROOT.glob(g) if p.is_file()}
    return out


def test_vercel_bundle_keeps_referenced_assets():
    fn = json.loads((ROOT / "vercel.json").read_text())["functions"]["app.py"]
    excluded = _excluded(fn["excludeFiles"])
    static = ROOT / "birds" / "web" / "static"
    refs = set()
    for page in [static / "index.html", static / "manifest.webmanifest"]:
        for path in re.findall(r'["(](/static/[^"\')?#]+)', page.read_text(encoding="utf-8")):
            refs.add("birds/web" + path)
    for page in (ROOT / "site").rglob("*.html"):
        for path in re.findall(r'(?:href|src)="(/assets/[^"?#]+)"', page.read_text(encoding="utf-8")):
            refs.add("site" + path)
    assert refs and any(r.endswith(".png") for r in refs)
    missing = sorted(r for r in refs if not (ROOT / r).is_file())
    assert not missing, missing
    assert not refs & excluded, sorted(refs & excluded)


def test_internal_site_files_are_not_served():
    from fastapi.testclient import TestClient

    from birds.web.server import create_app

    c = TestClient(create_app())
    for path in ("README.md", "COPY.md", "vercel.json", ".vercelignore"):
        assert c.get(f"/a-propos/{path}").status_code == 404, path
    assert c.get("/a-propos/assets/apple-touch-icon.png").status_code == 200
    assert c.get("/a-propos/assets/site.css").status_code == 200
    assert c.get("/a-propos/demarche").status_code == 200
