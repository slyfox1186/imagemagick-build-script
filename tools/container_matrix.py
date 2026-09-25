#!/usr/bin/env python3
"""Container validation matrix over the supported OS images.

    python3 tools/container_matrix.py <lint|apt|resolve|full> [image ...]

Levels:
  lint    - linter and offline test suite inside each image
  apt     - required-package availability gate inside each image
  resolve - every upstream version resolver inside each image (network)
  full    - complete non-root build (NOPASSWD sudo) driven end to end; success
            implies the builder's own staged and live validation passed (hours)

Containers are kept alive (named magick-matrix-*) so a failed full build can be
rerun incrementally after a fix; completion markers survive. Remove them with:
docker rm -f $(docker ps -aq --filter name=magick-matrix-)

Supported images ship Python older than 3.12 (Ubuntu 22.04 has 3.10), so setup
installs Miniforge for the build user and creates the launcher's environment,
exactly as the launcher would find it on a real host.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGES = ("debian:12", "debian:13", "ubuntu:22.04", "ubuntu:24.04")
LEVELS = ("lint", "apt", "resolve", "full")
HOME = "/home/builder"
ENVIRONMENT_PYTHON = f"{HOME}/miniforge3/envs/install-imagemagick/bin/python"
MINIFORGE = (
    "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
)
DEV_TOOLS = "pytest==9.1.1 ruff==0.16.8 mypy==2.3.1"

ROOT_SETUP = """
set -e
export DEBIAN_FRONTEND=noninteractive
apt update -q >/dev/null
apt install -y -q sudo curl git ca-certificates python3 xz-utils bzip2 procps >/dev/null
id builder >/dev/null 2>&1 || useradd -m -s /bin/bash builder
printf 'builder ALL=(ALL) NOPASSWD: ALL\\n' > /etc/sudoers.d/builder
chmod 440 /etc/sudoers.d/builder
"""

BUILDER_SETUP = f"""
set -e
cd {HOME}
if [ ! -x miniforge3/bin/conda ]; then
    curl --proto '=https' --tlsv1.2 -fsSL -o miniforge.sh {MINIFORGE}
    bash miniforge.sh -b -p {HOME}/miniforge3 >/dev/null
    rm -f miniforge.sh
fi
if [ ! -x {ENVIRONMENT_PYTHON} ]; then
    miniforge3/bin/conda create -q -y -p {HOME}/miniforge3/envs/install-imagemagick \\
        -c conda-forge --override-channels python=3.14 >/dev/null
    {ENVIRONMENT_PYTHON} -m pip install -q {DEV_TOOLS}
fi
"""

LEVEL_COMMANDS = {
    "lint": f"{ENVIRONMENT_PYTHON} run_linter.py && {ENVIRONMENT_PYTHON} -m pytest -q",
    "apt": f"sudo apt update -q >/dev/null && {ENVIRONMENT_PYTHON} tools/check_apt_availability.py",
    "resolve": f"{ENVIRONMENT_PYTHON} tools/resolve_versions.py",
    "full": "python3 build-magick.py --build </dev/null",
}


def docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *arguments], text=True, capture_output=True, check=check)


def as_builder(name: str, script: str) -> int:
    return subprocess.run(
        ["docker", "exec", "-u", "builder", "-w", f"{HOME}/repo", "-e", f"HOME={HOME}", name]
        + ["bash", "-c", script],
        check=False,
    ).returncode


def container_name(image: str) -> str:
    return "magick-matrix-" + re.sub(r"[^A-Za-z0-9]", "-", image)


def project_files() -> list[str]:
    """Tracked and new files plus `.git` (the linter lists files through Git).

    Never the ignored ones: a local build root alone holds gigabytes.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8", "surrogateescape")
    names = [name for name in listed.split("\0") if name and (REPO_ROOT / name).exists()]
    return [".git", *names]


def copy_project(name: str) -> None:
    with subprocess.Popen(
        ["tar", "-C", str(REPO_ROOT), "--null", "-T", "-", "-cf", "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    ) as archive:
        assert archive.stdin is not None and archive.stdout is not None
        receive = subprocess.Popen(
            ["docker", "exec", "-i", name, "tar", "-C", f"{HOME}/repo", "-xf", "-"],
            stdin=archive.stdout,
        )
        archive.stdout.close()
        archive.stdin.write("\0".join(project_files()).encode("utf-8", "surrogateescape"))
        archive.stdin.close()
        if receive.wait() != 0 or archive.wait() != 0:
            raise RuntimeError("copying the project into the container failed")


def ensure_container(image: str) -> str:
    name = container_name(image)
    running = docker("ps", "--format", "{{.Names}}").stdout.split()
    if name not in running:
        docker("rm", "-f", name, check=False)
        docker("run", "-d", "--name", name, image, "sleep", "infinity")
        docker("exec", name, "bash", "-c", ROOT_SETUP)
    # Refresh the repository copy every time so fixes propagate; the builder
    # home (markers, caches, the Conda environment) is deliberately preserved.
    docker("exec", name, "bash", "-c", f"rm -rf {HOME}/repo && mkdir {HOME}/repo")
    copy_project(name)
    docker("exec", name, "chown", "-R", "builder:builder", HOME)
    if as_builder(name, BUILDER_SETUP) != 0:
        raise RuntimeError("builder environment setup failed")
    return name


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in LEVELS:
        print(f"usage: container_matrix.py <{'|'.join(LEVELS)}> [image ...]", file=sys.stderr)
        return 2
    level, images = argv[0], argv[1:] or list(IMAGES)
    overall = 0
    for image in images:
        print(f"===== {level} : {image} =====", flush=True)
        try:
            name = ensure_container(image)
        except (subprocess.CalledProcessError, RuntimeError) as error:
            print(
                f"===== {level} : {image} : CONTAINER SETUP FAILED ({error}) =====", file=sys.stderr
            )
            overall = 1
            continue
        status = as_builder(name, LEVEL_COMMANDS[level])
        print(f"===== {level} : {image} : {'OK' if status == 0 else 'FAILED'} =====", flush=True)
        overall |= int(status != 0)
    return overall


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
