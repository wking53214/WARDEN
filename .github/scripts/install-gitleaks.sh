#!/usr/bin/env bash
# Install a pinned gitleaks release, refusing anything whose sha256 is not the
# one written in the workflow.
#
# Usage: install-gitleaks.sh VERSION SHA256 [INSTALL_DIR]
#
# SHA256 is the digest of gitleaks_<VERSION>_linux_x64.tar.gz as published in the
# release's own gitleaks_<VERSION>_checksums.txt. It lives in the workflow, in
# review, so a replaced release asset cannot change what the job runs: a
# mismatch exits 1 before anything is extracted or installed.
#
# To bump: fetch the new tarball and the release checksums file, confirm the two
# agree, and change VERSION and SHA256 in tests.yml (both jobs) together.
set -euo pipefail

version="${1:?usage: install-gitleaks.sh VERSION SHA256 [INSTALL_DIR]}"
expected="${2:?usage: install-gitleaks.sh VERSION SHA256 [INSTALL_DIR]}"
dest="${3:-/usr/local/bin}"
base="${GITLEAKS_BASE_URL:-https://github.com/gitleaks/gitleaks/releases/download}"

if ! [[ "$expected" =~ ^[0-9a-f]{64}$ ]]; then
  echo "::error::gitleaks sha256 '$expected' is not 64 lowercase hex characters" >&2
  exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
archive="$work/gitleaks_${version}_linux_x64.tar.gz"

curl -sSfL -o "$archive" "$base/v${version}/gitleaks_${version}_linux_x64.tar.gz"
actual="$(sha256sum "$archive" | cut -d' ' -f1)"
if [ "$actual" != "$expected" ]; then
  echo "::error::gitleaks ${version} sha256 mismatch: expected ${expected}, downloaded file is ${actual}. Nothing was installed." >&2
  exit 1
fi

tar -xzf "$archive" -C "$work" gitleaks
if [ -w "$dest" ]; then
  mv "$work/gitleaks" "$dest/gitleaks"
else
  sudo mv "$work/gitleaks" "$dest/gitleaks"
fi
"$dest/gitleaks" version
