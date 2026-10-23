#!/usr/bin/env python3
"""Check real package installation without touching the operator manager HOME."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def check(curator):
    # Claim: exercise the documented activated ordinary venv, not a test-only
    # Python launcher that could mask Curator canonicalizing its symlink.
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if not virtual_env or Path(sys.prefix).resolve() != Path(virtual_env).resolve() or sys.prefix == sys.base_prefix:
        raise AssertionError("activate the provisioned ordinary venv before the installed-shim test")
    scratch = ROOT / ".temp"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="curator-check-", dir=scratch) as directory:
        root = Path(directory)
        project, manager, home = (root / name for name in ("project", "manager", "home"))
        for path in (project, manager, home, root / "tmp"):
            path.mkdir()
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(HOME=str(home), USERPROFILE=str(home), CURATOR_HOME=str(manager),
                   CURATOR_CONFIG=str(manager / "config.json"), XDG_CONFIG_HOME=str(home / ".config"),
                   XDG_CACHE_HOME=str(home / ".cache"), XDG_DATA_HOME=str(home / ".local/share"),
                   TMPDIR=str(root / "tmp"))

        def invoke(*args):
            result = subprocess.run([str(curator), *map(str, args)], cwd=project, env=env,
                                    text=True, capture_output=True)
            if result.returncode:
                raise AssertionError(f"curator {args[0]} exited {result.returncode}: {result.stdout}{result.stderr}")
            return result.stdout

        source = root / "skills/platform-book"
        invoke("bootstrap", "--non-interactive", "--skills-root", root / "skills")
        invoke("project", "add", "sample", project, "--agents", "codex_cli")
        def git(*args, cwd=ROOT):
            result = subprocess.run(["git", *map(str, args)], cwd=cwd, env=env,
                                    capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(f"fixture git exited {result.returncode}: {result.stderr}")
            return result.stdout.strip()
        revision = git("rev-parse", "HEAD")
        git("clone", "--no-hardlinks", ROOT, source)
        (project / "Skillfile.json").write_text(json.dumps({
            "schema_version": 1, "agents": ["codex_cli"],
            "skills": [{"name": "platform-book", "source": "platform-book", "revision": revision}]}))
        invoke("install", "sample", "--fix-gitignore")
        marker = json.loads((project / ".agents/skills/platform-book/.csk-install.json").read_text())
        if marker.get("hash_version") != 2:
            raise AssertionError("installation did not use v2 content identity")
        if (project / ".agents/skills/platform-book/assets").exists():
            raise AssertionError("runtime assets leaked into prompt context")
        shim = project / ".agents/bin/platform-book"
        if not shim.is_file():
            raise AssertionError("exported shim missing")
        def ready():
            result = subprocess.run([str(shim), "ready"], cwd=project, env=env, text=True, capture_output=True)
            if result.returncode or "ready" not in result.stdout:
                raise AssertionError(f"installed readiness failed: {result.stdout}{result.stderr}")
        ready()
        # Claim: invalid activation cannot silently fall back to base Python.
        valid_venv = env["VIRTUAL_ENV"]
        env["VIRTUAL_ENV"] = str(root / "missing-venv")
        refused = subprocess.run([str(shim), "ready"], cwd=project, env=env, text=True, capture_output=True)
        if refused.returncode != 2 or "activated VIRTUAL_ENV has no Python interpreter" not in refused.stderr:
            raise AssertionError(f"invalid activation did not refuse: {refused.stdout}{refused.stderr}")
        env["VIRTUAL_ENV"] = valid_venv
        # Claim: a changed source font cannot silently alter the locked runtime.
        font = source / "assets/fonts/PTM55FT.ttf"
        font.write_bytes(b"changed source bytes")
        ready()
        output = root / "installed.pdf"
        result = subprocess.run([str(shim), "build", str(ROOT / "examples/two-page"), str(output),
                                 "--expected-pages", "2"], env=env, cwd=project, text=True, capture_output=True)
        if result.returncode or not output.is_file():
            raise AssertionError(f"installed build failed: {result.stdout}{result.stderr}")
        # Claim: deleting an installed runtime asset is detected, rather than
        # accidentally resolving an intact asset in the source checkout.
        fonts = [p for p in manager.rglob("PTM55FT.ttf") if p.read_bytes() != b"changed source bytes"]
        if not fonts:
            raise AssertionError("frozen runtime font not found")
        for path in fonts:
            path.chmod(0o600)
            path.unlink()
        result = subprocess.run([str(shim), "ready"], cwd=project, env=env, text=True, capture_output=True)
        if result.returncode != 2 or "missing or modified bundled font: PTM55FT.ttf" not in result.stderr:
            raise AssertionError(f"missing frozen font did not produce its intended refusal: {result.stderr}")
        print("Curator: exact-revision install, v2 marker, shim build, source-drift isolation and missing-runtime negative: passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curator", default="curator")
    args = parser.parse_args()
    executable = shutil.which(args.curator)
    if not executable:
        parser.error("curator executable missing")
    check(Path(executable).resolve())
