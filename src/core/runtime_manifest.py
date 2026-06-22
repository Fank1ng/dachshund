"""Build/runtime manifest helpers for update integrity checks."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Iterable

from version import app_version


BUILD_MANIFEST = "build_manifest.json"
RUNTIME_MANIFEST = "runtime_manifest.json"
DEFAULT_MANIFEST_PATHS = (
    "VERSION",
    "account_manager.py",
    "config.py",
    "proxy.py",
    "proxy_core.py",
    "quota_tracker.py",
    "service_manager.py",
    "usage_stats.py",
    "version.py",
    "runtime_manifest.py",
    "static/index.html",
)


class ManifestError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_manifest(root: Path, *, manifest_name: str = BUILD_MANIFEST, paths: Iterable[str] = DEFAULT_MANIFEST_PATHS) -> dict:
    root = Path(root)
    files = {}
    missing = []
    for rel in paths:
        path = root / rel
        if path.is_file():
            files[rel] = file_sha256(path)
        else:
            missing.append(rel)
    return {
        "schema": 1,
        "manifest_name": manifest_name,
        "version": app_version(root),
        "built_at": int(time.time()),
        "files": files,
        "missing": missing,
    }


def write_manifest(root: Path, *, manifest_name: str = BUILD_MANIFEST) -> dict:
    root = Path(root)
    manifest = generate_manifest(root, manifest_name=manifest_name)
    (root / manifest_name).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def read_manifest(root: Path, *, manifest_name: str = BUILD_MANIFEST) -> dict:
    path = Path(root) / manifest_name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ManifestError(f"manifest missing: {path}") from e
    except json.JSONDecodeError as e:
        raise ManifestError(f"manifest unreadable: {path}") from e
    if not isinstance(data, dict):
        raise ManifestError(f"manifest invalid: {path}")
    return data


def compare_manifests(expected: dict, observed: dict) -> dict:
    expected_files = expected.get("files") if isinstance(expected.get("files"), dict) else {}
    observed_files = observed.get("files") if isinstance(observed.get("files"), dict) else {}
    missing = sorted(set(expected_files) - set(observed_files))
    extra = sorted(set(observed_files) - set(expected_files))
    changed = sorted(
        name for name in set(expected_files) & set(observed_files)
        if expected_files.get(name) != observed_files.get(name)
    )
    version_match = expected.get("version") == observed.get("version")
    ok = version_match and not expected.get("missing") and not observed.get("missing") and not missing and not changed
    return {
        "ok": ok,
        "version_match": version_match,
        "expected_version": expected.get("version", ""),
        "observed_version": observed.get("version", ""),
        "missing": missing,
        "extra": extra,
        "changed": changed,
        "expected_missing": expected.get("missing") or [],
        "observed_missing": observed.get("missing") or [],
    }


def compare_runtime_to_bundle(bundle_runtime: Path, runtime: Path) -> dict:
    bundle_manifest = read_manifest(bundle_runtime, manifest_name=BUILD_MANIFEST)
    runtime_manifest = read_manifest(runtime, manifest_name=RUNTIME_MANIFEST)
    return compare_manifests(bundle_manifest, runtime_manifest)
