#!/usr/bin/env python3
"""Run required native CI in the coherent Arch snapshot approved by shared policy."""

import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

INSTALL_AND_TEST = """\
cat > /tmp/smplos-ci-pacman.conf <<EOF
[options]
Architecture = x86_64
SigLevel = Required DatabaseOptional
LocalFileSigLevel = Optional
[core]
Server = https://archive.archlinux.org/repos/$1/core/os/x86_64
[extra]
Server = https://archive.archlinux.org/repos/$1/extra/os/x86_64
EOF
# Double -u moves the ENTIRE bootstrap system to the snapshot, including downgrades.
# Never install just an old compositor against current rolling libraries.
pacman --config /tmp/smplos-ci-pacman.conf -Syyuu --noconfirm --needed hyprland python lua libxkbcommon
pacman --config /tmp/smplos-ci-pacman.conf -Dk
export XDG_RUNTIME_DIR=/tmp/smplos-ci-runtime
mkdir -m 700 "$XDG_RUNTIME_DIR"
python3 tools/ci_baseline.py --verify-installed
python3 --version
tools/keybind-check doctor
args=()
if [[ -n "$2" ]]; then args=(-k "$2"); fi
PYTHONPATH=tests python3 -m unittest test_keybindings -v "${args[@]}"
"""


def load_policy(root=ROOT):
    directory = root / "src/shared/update-policy"
    policy = json.loads((directory / "ci-baseline.json").read_text())
    if not isinstance(policy, dict) or set(policy) != {"image", "snapshot", "hyprland_version"}:
        raise ValueError("ci-baseline.json must contain image, snapshot and hyprland_version only")
    if not all(isinstance(value, str) for value in policy.values()):
        raise ValueError("CI baseline values must be strings")
    if not re.fullmatch(r"docker\.io/library/archlinux@sha256:[0-9a-f]{64}", policy["image"]):
        raise ValueError("CI bootstrap image must be an immutable official Arch Linux digest")
    snapshot = policy["snapshot"]
    if not re.fullmatch(r"\d{4}/\d{2}/\d{2}", snapshot):
        raise ValueError("CI snapshot must be an explicit YYYY/MM/DD Arch archive date")
    datetime.date.fromisoformat(snapshot.replace("/", "-"))
    series = re.findall(r'^HYPRLAND_SERIES="(\d+\.\d+)"\s*$', (
        directory / "critical-bundle.conf").read_text(), re.MULTILINE)
    if len(series) != 1:
        raise ValueError("critical-bundle.conf must declare one explicit HYPRLAND_SERIES")
    if not re.fullmatch(re.escape(series[0]) + r"\.\d+-\d+", policy["hyprland_version"]):
        raise ValueError("CI Hyprland package must match the approved HYPRLAND_SERIES")
    return policy


def output(*args):
    return subprocess.check_output(args, text=True)


def verify_installed(policy):
    installed = dict(line.split() for line in output("pacman", "-Q").splitlines())
    available = {}
    for line in output("pacman", "--config", "/tmp/smplos-ci-pacman.conf", "-Sl").splitlines():
        _, name, version, *_ = line.split()
        available[name] = version
    mismatches = [f"{name}: installed {version}, snapshot {available.get(name, 'MISSING')}"
                  for name, version in installed.items() if available.get(name) != version]
    if mismatches:
        raise ValueError("Installed packages differ from the CI snapshot:\n" + "\n".join(mismatches))
    if installed.get("hyprland") != policy["hyprland_version"]:
        raise ValueError(f"Expected hyprland {policy['hyprland_version']}, "
                         f"installed {installed.get('hyprland', 'MISSING')}")
    version = output("Hyprland", "--version")
    upstream = policy["hyprland_version"].rsplit("-", 1)[0]
    if not re.search(r"\bHyprland\s+" + re.escape(upstream) + r"(?=\s|$)", version):
        raise ValueError(f"Hyprland executable does not match the baseline: {version}")
    print(f"Verified Arch snapshot {policy['snapshot']}; complete installed package inventory:",
          flush=True)
    print("\n".join(f"{name} {version}" for name, version in sorted(installed.items())), flush=True)
    print(version, flush=True)


def container_command(policy, runtime, test_filter):
    return [
        runtime, "run", "--rm", "--platform", "linux/amd64",
        "--volume", f"{ROOT}:/src:ro", "--workdir", "/src",
        "--env", "KEYBIND_CHECK_REQUIRE=lua,xkbcommon,hyprland",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        policy["image"], "bash", "-euo", "pipefail", "-c", INSTALL_AND_TEST,
        "ci-native", policy["snapshot"], test_filter,
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=("docker", "podman"), default="docker")
    parser.add_argument("--filter", default="")
    parser.add_argument("--check", action="store_true", help="validate policy without a container")
    parser.add_argument("--verify-installed", action="store_true",
                        help="check the installed snapshot inside the disposable container")
    args = parser.parse_args()
    try:
        policy = load_policy()
        if args.verify_installed:
            verify_installed(policy)
        else:
            print(json.dumps(policy, sort_keys=True), flush=True)
            if not args.check:
                subprocess.run(container_command(policy, args.runtime, args.filter), check=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"CI baseline error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
