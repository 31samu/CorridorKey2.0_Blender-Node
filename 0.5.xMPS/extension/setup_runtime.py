# SPDX-License-Identifier: GPL-3.0-or-later
"""Install the standalone Apple Silicon MPS runtime without importing it into Blender."""

import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import sys

PYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/20261110/"
    "cpython-3.12.16%2B20261110-aarch64-apple-darwin-install_only.tar.gz"
)
PYTHON_HASH = "e956e60bc9465d577ef8062059aa05cd3a2665b4b8678a2ed24e432368330b8f"
PYTHON_SIZE = 25_371_130
BACKEND_REVISION = "ccb897c703eb272212323f3d45683d577bfb2e84"
BACKEND_URL = f"https://codeload.github.com/jslinker/CorridorKey2.0/tar.gz/{BACKEND_REVISION}"
BACKEND_HASH = "c946a92e9983b86c5467fdecc2490b59c7d2cd6be77264601fcda16941392fe5"
MODEL_REVISION = "cf44a8db3f024bb49fd59daa408848ccf05f7477"
UTILS3D_REVISION = "83bfa5bda008803f6521ce9547f94023b8afeddd"
MODEL_FILES = (
    "weights/corridorkey_v2.safetensors",
    "weights/foundation_stats.safetensors",
    "vfms/moge/model.pt",
    "vfms/cradio/C-RADIOv4-SO400M/model.safetensors",
    "vfms/rvm/pretrain_rvm_small16_256_204031069.npz",
)


def installed_paths(root):
    python, checkout, ffmpeg = root / "venv/bin/python", root / "backend", root / "ffmpeg"
    if (
        (root / "ready").is_file()
        and os.access(python, os.X_OK)
        and os.access(ffmpeg, os.X_OK)
        and (checkout / "infer.py").is_file()
        and all((checkout / name).is_file() for name in MODEL_FILES)
    ):
        return python, checkout, ffmpeg


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
    if installed_paths(root):
        return
    ready = root / "ready"
    ready.unlink(missing_ok=True)
    print("SETUP 1 Downloading Python and the MPS backend", flush=True)
    python = root / "python/bin/python3.12"
    checkout = root / "backend"
    for url, digest, folder, relative_root, required_file, size in (
        (PYTHON_URL, PYTHON_HASH, python.parents[1], "python", python, PYTHON_SIZE),
        (BACKEND_URL, BACKEND_HASH, checkout, f"CorridorKey2.0-{BACKEND_REVISION}", checkout / "infer.py", None),
    ):
        if not required_file.is_file():
            archive = root / f"{folder.name}.tar.gz"
            fetch(url, archive, digest, size)
            unpack(archive, folder, relative_root)
            archive.unlink(missing_ok=True)

    print("SETUP 2 Installing PyTorch and FFmpeg", flush=True)
    environment = root / "venv"
    env_python = environment / "bin/python"
    dependencies_ready = root / "dependencies-ready"
    if not env_python.is_file() or not dependencies_ready.is_file():
        subprocess.run([python, "-m", "venv", environment], check=True)
        requirements = root / "requirements.txt"
        requirements.write_text((checkout / "requirements.txt").read_text().replace(
            f"git+https://github.com/EasternJournalist/utils3d.git@{UTILS3D_REVISION}",
            f"https://codeload.github.com/EasternJournalist/utils3d/tar.gz/{UTILS3D_REVISION}",
        ))
        subprocess.run([
            env_python, "-I", "-m", "pip", "--isolated", "--disable-pip-version-check",
            "install", "--cache-dir", root / "pip-cache", "--index-url", "https://pypi.org/simple",
            "--timeout", "45", "--retries", "4", "-r", requirements,
            "torch==2.9.1", "torchvision==0.24.1", "imageio-ffmpeg==0.6.0",
        ], check=True)
        subprocess.run([env_python, "-I", "-m", "pip", "--isolated", "check"], check=True)
        dependencies_ready.touch()
    ffmpeg = root / "ffmpeg"
    binary = subprocess.check_output([
        env_python, "-I", "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())",
    ], text=True, env={k: v for k, v in os.environ.items() if k != "IMAGEIO_FFMPEG_EXE"}).strip()
    ffmpeg.unlink(missing_ok=True)
    ffmpeg.symlink_to(os.path.relpath(binary, root))
    subprocess.run([
        env_python, "-I", "-c",
        "import torch; assert torch.backends.mps.is_available(), 'PyTorch MPS is unavailable'; "
        "x = torch.ones((16, 16), device='mps', dtype=torch.bfloat16); x @ x; torch.mps.synchronize()",
    ], check=True)

    print("SETUP 3 Downloading CorridorKey and foundation models", flush=True)
    subprocess.run([
        env_python, "-E", "-s", "-u", checkout / "scripts/download_weights.py",
        "--corridorkey_revision", MODEL_REVISION,
    ], check=True, cwd=checkout, env={**os.environ, "HF_HOME": str(root / "hf"), "HF_HUB_OFFLINE": "0"})

    print("SETUP 4 Verifying the MPS runtime", flush=True)
    subprocess.run([ffmpeg, "-version"], check=True)
    subprocess.run([env_python, "-E", "-s", checkout / "infer.py", "--help"], check=True, cwd=checkout)
    subprocess.run([
        env_python, "-E", "-s", "-c",
        "from corridorkey.runtime import RuntimePaths; RuntimePaths.from_package('.').validate()",
    ], check=True, cwd=checkout)
    ready.touch()
    shutil.rmtree(root / "pip-cache", ignore_errors=True)


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / "setup.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Setup is already running in another Blender window.") from None
        install(root)
