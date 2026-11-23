# SPDX-License-Identifier: GPL-3.0-or-later
"""Install the standalone MLX runtime without importing it into Blender."""

import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

PYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/20261110/"
    "cpython-3.12.16%2B20261110-aarch64-apple-darwin-install_only.tar.gz"
)
PYTHON_HASH = "e956e60bc9465d577ef8062059aa05cd3a2665b4b8678a2ed24e432368330b8f"
PYTHON_SIZE = 25_371_130
BACKEND_REVISION = "74065491ebd2eddea494ab34c15a6d84d7415353"
BACKEND_URL = f"https://codeload.github.com/peterteravskis/corridorkey-v2-mlx/tar.gz/{BACKEND_REVISION}"
BACKEND_HASH = "6fa9d5698ad95c53b1dec9551bfd0df0f78eb94d256ea532a21a43a13ba1c4c6"
BACKEND_SIZE = 23_055_277
MODEL_REVISION = "3c75d4756579e2bdd21307c64a1af381bde1cdc1"
MODEL_URL = f"https://huggingface.co/cdelta/CorridorKey-v2-MLX-fp16/resolve/{MODEL_REVISION}/"
MODEL_FILES = json.loads(Path(__file__).with_name("setup-model-files.json").read_text())
LARGE_MODEL_FILES = json.loads(Path(__file__).with_name("model-1536x1024-files.json").read_text())


def verified(path, digest):
    if not path.is_file():
        return False
    with path.open("rb") as stream:
        if len(digest) == 40:
            # Hugging Face reports Git blob IDs for files outside Git LFS.
            checksum = hashlib.sha1(f"blob {path.stat().st_size}\0".encode())
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
        else:
            checksum = hashlib.file_digest(stream, "sha256")
        return checksum.hexdigest() == digest


def fetch(url, target, digest, size=None):
    if verified(target, digest):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    if not verified(partial, digest):
        if size is not None and partial.is_file() and partial.stat().st_size >= size:
            partial.unlink()
        command = [
            "/usr/bin/curl", "--fail", "--silent", "--show-error", "--location",
            "--proto", "=https", "--proto-redir", "=https", "--connect-timeout", "30",
            "--retry", "3", "--speed-limit", "1024", "--speed-time", "60",
            "--output", str(partial),
        ]
        resume = partial.is_file() and partial.stat().st_size > 0
        result = subprocess.run([*command, *(["--continue-at", "-"] if resume else []), url])
        if resume and result.returncode in (33, 36):  # Server rejected the range request.
            partial.unlink(missing_ok=True)
            result = subprocess.run([*command, url])
        result.check_returncode()
        if not verified(partial, digest):
            partial.unlink()
            raise ValueError(f"Checksum mismatch for {target.name}")
    partial.replace(target)


def unpack(archive, destination, relative_root):
    if destination.exists():
        return
    staging = destination.with_name(destination.name + ".unpacking")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(staging, filter="data")
    (staging / relative_root).rename(destination)
    shutil.rmtree(staging)


def install(root):
    ready = root / "ready"
    models = root / "models"
    remaining = sum(
        max(0, metadata["size"] - bytes_on_disk(models / name))
        for name, metadata in MODEL_FILES.items()
    )
    if shutil.disk_usage(root).free < remaining + 2_000_000_000:
        raise RuntimeError("CorridorKey setup needs at least 5 GB of free disk space.")
    ready.unlink(missing_ok=True)
    print("SETUP 1 Downloading Python runtime", flush=True)
    python_archive = root / "python.tar.gz"
    if not (root / "python").is_dir():
        fetch(PYTHON_URL, python_archive, PYTHON_HASH, PYTHON_SIZE)
        unpack(python_archive, root / "python", "python")
    python_archive.unlink(missing_ok=True)

    print("SETUP 1 Downloading CorridorKey backend", flush=True)
    backend_archive = root / "backend.tar.gz"
    if not (root / "backend").is_dir():
        fetch(BACKEND_URL, backend_archive, BACKEND_HASH, BACKEND_SIZE)
        unpack(backend_archive, root / "backend", f"corridorkey-v2-mlx-{BACKEND_REVISION}")
    backend_archive.unlink(missing_ok=True)

    print("SETUP 1 Installing runtime dependencies", flush=True)
    python = root / "python/bin/python3.12"
    environment = root / "venv"
    subprocess.run([python, "-m", "venv", environment], check=True)
    env_python = environment / "bin/python"
    subprocess.run([
        env_python, "-m", "pip", "--isolated", "--disable-pip-version-check", "install",
        "--cache-dir", root / "pip-cache", "--index-url", "https://pypi.org/simple",
        "--timeout", "45", "--retries", "5", root / "backend",
    ], check=True)
    subprocess.run([env_python, "-m", "pip", "--disable-pip-version-check", "check"], check=True)

    print("SETUP 2 Downloading 720p model", flush=True)
    for name, metadata in MODEL_FILES.items():
        fetch(MODEL_URL + name, models / name, metadata["sha256"], metadata["size"])

    print("SETUP 3 Verifying runtime", flush=True)
    subprocess.run([
        env_python, "-c",
        "import cv2, torch, mlx.core as mx; print(mx.device_info()); mx.eval(mx.ones(1))",
    ], check=True)
    subprocess.run([environment / "bin/corridorkey-mlx", "--version"], check=True)
    ready.touch()


def bytes_on_disk(path):
    for candidate in (path, path.with_name(path.name + ".part")):
        try:
            return candidate.stat().st_size
        except FileNotFoundError:
            pass
    return 0


def install_large_model(models, step=2):
    print(f"SETUP {step} Downloading 1536 × 1024 model", flush=True)
    downloads = []
    for name, metadata in LARGE_MODEL_FILES.items():
        target = models / name
        existing = models / name.replace("1024x1536-t1", "768x1280-t1")
        digest = metadata.get("sha256") or metadata["git_sha1"]
        if not target.exists() and verified(existing, digest):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.hardlink_to(existing)
        else:
            downloads.append((name, target, digest, metadata["size"]))
    remaining = sum(max(0, size - bytes_on_disk(target)) for _, target, _, size in downloads)
    if shutil.disk_usage(models).free < remaining:
        raise RuntimeError("There is not enough free space for the 1536 × 1024 model.")
    for name, target, digest, size in downloads:
        fetch(MODEL_URL + name, target, digest, size)


def main(root, extra_models=None, include_large_model=False):
    root.mkdir(parents=True, exist_ok=True)
    with (root / "setup.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Setup is already running in another Blender window.") from None
        if extra_models is None:
            install(root)
            if include_large_model:
                install_large_model(root / "models", step=4)
        else:
            install_large_model(extra_models)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    model_options = parser.add_mutually_exclusive_group()
    model_options.add_argument("extra_models", type=Path, nargs="?")
    model_options.add_argument("--include-large-model", action="store_true")
    args = parser.parse_args()
    main(args.root, args.extra_models, args.include_large_model)
