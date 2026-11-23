# SPDX-License-Identifier: GPL-3.0-or-later
"""Install the experimental CUDA runtime in an isolated Windows user directory."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile

PYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/20261110/"
    "cpython-3.12.16%2B20261110-x86_64-pc-windows-msvc-install_only.tar.gz"
)
PYTHON_HASH = "e23fe5b16926de1d81661b1a97352e89fb167549c55a6825796ccd0f32ec7f1b"
REVISION = "485f5e9ab759ead6138cc990776184b59d6ea971"
MODEL_REVISION = "cf44a8db3f024bb49fd59daa408848ccf05f7477"
BACKEND_URL = f"https://codeload.github.com/nikopueringer/CorridorKey2.0/tar.gz/{REVISION}"
FFMPEG_RELEASE = "ffmpeg-8.1.2-essentials_build"
FFMPEG_URL = f"https://github.com/GyanD/codexffmpeg/releases/download/8.1.2/{FFMPEG_RELEASE}.zip"
FFMPEG_HASH = "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"
PYTHON_PATH = Path("py/python.exe")
BACKEND_PATH = Path("ck")
FFMPEG_PATH = Path("ff/bin/ffmpeg.exe")


def installed_paths(root):
    python, checkout, ffmpeg = root / PYTHON_PATH, root / BACKEND_PATH, root / FFMPEG_PATH
    if (root / "ready").is_file() and all(
        path.is_file() for path in (
            python, checkout / "infer.py", ffmpeg,
            checkout / "weights/corridorkey_v2.safetensors", checkout / "weights/foundation_stats.safetensors",
            checkout / "vfms/moge/model.pt", checkout / "vfms/cradio/C-RADIOv4-SO400M/model.safetensors",
            checkout / "vfms/rvm/pretrain_rvm_small16_256_204031069.npz",
        )
    ):
        return python, checkout, ffmpeg


def fetch(url, target, checksum=None):
    partial = target.with_suffix(".part")
    for attempt in range(3):
        try:
            with urlopen(url, timeout=45) as response, partial.open("wb") as stream:
                if not response.geturl().startswith("https://"):
                    raise ValueError("Download was redirected away from HTTPS.")
                size = response.headers.get("Content-Length")
                shutil.copyfileobj(response, stream, length=1024 * 1024)
            if size and partial.stat().st_size != int(size):
                raise OSError(f"Incomplete download: {target.name}")
            if checksum is not None:
                with partial.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
                        raise OSError(f"Checksum mismatch: {target.name}")
            partial.replace(target)
            return
        except OSError as error:
            if attempt == 2:
                raise
            print(f"Retrying {target.name}: {error}", flush=True)


def install_archive(url, destination, top_level, required_file, checksum=None, zip_archive=False):
    if (destination / required_file).is_file():
        return
    with tempfile.TemporaryDirectory(prefix="dl-", dir=destination.parent) as work:
        work = Path(work)
        archive = work / "download"
        fetch(url, archive, checksum)
        if zip_archive:
            with ZipFile(archive) as source:
                source.extractall(work)
        else:
            with tarfile.open(archive, "r:gz") as source:
                source.extractall(work, filter="data")
        extracted = work / top_level
        if not (extracted / required_file).is_file():
            raise RuntimeError(f"The downloaded archive is missing {required_file}.")
        if destination.exists():
            shutil.rmtree(destination)
        extracted.rename(destination)


def run(*args, **kwargs):
    subprocess.run(args, check=True, creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)


def install(root):
    ready = root / "ready"
    python = root / PYTHON_PATH
    checkout = root / BACKEND_PATH
    ffmpeg = root / FFMPEG_PATH
    if installed_paths(root):
        return
    ready.unlink(missing_ok=True)
    dependencies_ready = root / "dependencies-ready"
    if not python.is_file():
        dependencies_ready.unlink(missing_ok=True)
        if shutil.disk_usage(root).free < 12_000_000_000:
            raise RuntimeError("Allow at least 12 GB of free space for first-time CUDA setup.")

    print("SETUP 1 Downloading Python, FFmpeg and CorridorKey", flush=True)
    install_archive(PYTHON_URL, python.parent, "python", "python.exe", PYTHON_HASH)
    install_archive(FFMPEG_URL, root / "ff", FFMPEG_RELEASE, "bin/ffmpeg.exe", FFMPEG_HASH, zip_archive=True)
    install_archive(BACKEND_URL, checkout, f"CorridorKey2.0-{REVISION}", "infer.py")

    print("SETUP 2 Installing PyTorch and checking the NVIDIA GPU", flush=True)
    if not dependencies_ready.is_file():
        run(python, "-I", "-m", "ensurepip", "--upgrade")
        pip = (python, "-I", "-m", "pip", "--isolated", "--disable-pip-version-check")
        options = ("--cache-dir", root / "pip-cache", "--timeout", "45", "--retries", "4")
        run(*pip, "install", *options, "--index-url", "https://download.pytorch.org/whl/cu128",
            "torch==2.9.1+cu128", "torchvision==0.24.1+cu128")
        run(*pip, "install", *options, "--index-url", "https://pypi.org/simple",
            "-r", checkout / "requirements.txt", "torch==2.9.1+cu128", "torchvision==0.24.1+cu128")
        run(*pip, "check")
        dependencies_ready.touch()
    run(python, "-I", "-c",
        "import torch; "
        "assert torch.cuda.is_available(), 'CUDA unavailable. Check your NVIDIA driver.'; "
        "assert torch.cuda.get_device_capability()[0] >= 8, 'An RTX 30-series or newer GPU is required.'; "
        "print(torch.cuda.get_device_name(0)); "
        "x = torch.ones((16, 16), device='cuda', dtype=torch.bfloat16); x @ x; torch.cuda.synchronize()")

    print("SETUP 3 Downloading CorridorKey and foundation models", flush=True)
    run(python, "-E", "-s", "-X", "utf8", "-u", checkout / "scripts/download_weights.py",
        "--corridorkey_revision", MODEL_REVISION, cwd=checkout,
        env={**os.environ, "HF_HOME": str(root / "hf"), "HF_HUB_OFFLINE": "0"})

    print("SETUP 4 Verifying the CUDA runtime", flush=True)
    run(ffmpeg, "-version")
    run(python, "-E", "-s", "-u", checkout / "infer.py", "--help", cwd=checkout)
    run(python, "-E", "-s", "-c",
        "from corridorkey.runtime import RuntimePaths; RuntimePaths.from_package('.').validate()", cwd=checkout)
    ready.touch()
    shutil.rmtree(root / "pip-cache", ignore_errors=True)


def main(root):
    import msvcrt

    root.mkdir(parents=True, exist_ok=True)
    with (root / "setup.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError("Setup is already running in another Blender window.") from None
        install(root)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
