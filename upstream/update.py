#!/usr/bin/env python3
"""Import explicitly selected upstream thin-plugin release manifests."""

import argparse
import re
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent / "multus" / "manifests"
SOURCE = "https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni"
IMAGE = re.compile(r"(?m)^(\s*image:\s+)ghcr.io/k8snetworkplumbingwg/multus-cni:\S+$")


def release_manifest(version):
    """Keep the released deployment, pinning both thin-plugin images to its tag."""
    if not re.fullmatch(r"v\d+\.\d+\.\d+", version):
        raise ValueError(f"Expected a stable vMAJOR.MINOR.PATCH tag: {version}")
    url = f"{SOURCE}/{version}/deployments/multus-daemonset.yml"
    with urlopen(url, timeout=60) as response:
        upstream = response.read().decode("utf-8")
    manifest, count = IMAGE.subn(
        rf"\g<1>ghcr.io/k8snetworkplumbingwg/multus-cni:{version}", upstream
    )
    if count != 2:
        raise ValueError(f"Expected two thin-plugin images in {url}, found {count}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "versions", nargs="+", help="Explicit stable release tags to import"
    )
    parser.add_argument(
        "--check", action="store_true", help="Check existing bundles without writing"
    )
    args = parser.parse_args()
    for version in args.versions:
        manifest = release_manifest(version)
        path = ROOT / version / "multus-daemonset.yaml"
        if args.check or path.exists():
            if path.read_text() != manifest:
                raise ValueError(f"Bundle differs from pinned upstream release: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(manifest)
        print(f"{version}: {path}")


if __name__ == "__main__":
    main()
