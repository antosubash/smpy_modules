#!/usr/bin/env bash
# Installs Chromium for the e2e suite. apt runs only when Chromium can't start
# without it (#215).
#
# Background: the Azure Ubuntu mirror stalls. When it did, `playwright
# install-deps` sat out its whole 20-minute timeout inside one apt call (run
# 39790900372: every azure index `Ign`, then silence after the last InRelease
# from archive.ubuntu.com). This script avoids that:
#
#   1. Get the browser: from the cache, or downloaded from Playwright's CDN
#      (no apt involved).
#   2. Smoke check: launch headless Chromium and render a page. The runner
#      image usually already has every library it needs. If it starts, stop
#      here: apt never runs.
#   3. Otherwise run apt with a private config ($APT_CONFIG). It reads one
#      Ubuntu source (main + universe; release, -updates and -security; native
#      arch; no translations or command-not-found data). That comes to about
#      28 MB of indexes, against 37 MB for the runner's default sources, and
#      leaves out the third-party repos the image adds.
#      - `apt-get update` gets its own short timeout. If it fails, the source
#        moves from the runner's mirror list (Azure first) to
#        archive.ubuntu.com and the update runs once more.
#      - Then install only what `install-deps --dry-run` reports missing, with
#        --no-install-recommends, again under its own timeout.
#   4. Smoke check again. A failure here fails the step.
#
# The caller's `timeout 20m` is the hard cap for the whole script.
# Every path prints a `::notice::`, so the job summary shows which one ran.
#
# E2E_FORCE_APT=1 skips the first smoke check, and E2E_FORCE_APT=fallback also
# fails the first update on purpose. Both exist only to exercise these paths
# in CI. Nothing sets them by default.
set -euo pipefail

FORCE=${E2E_FORCE_APT:-}
ARCHIVE_URI=http://archive.ubuntu.com/ubuntu/
if [ -f /etc/apt/apt-mirrors.txt ]; then
  DEFAULT_URI=mirror+file:/etc/apt/apt-mirrors.txt
else
  DEFAULT_URI=$ARCHIVE_URI
fi
mirror_switched=false

log() { echo "[install-browsers] $*"; }

smoke_check() {
  timeout -k 10s 90s node -e '
    const { chromium } = require("@playwright/test");
    (async () => {
      const browser = await chromium.launch();
      const page = await browser.newPage();
      await page.setContent("<p>ok</p>");
      if ((await page.textContent("p")) !== "ok") throw new Error("render failed");
      await browser.close();
    })().catch((err) => { console.error(err.message); process.exit(1); });
  '
}

# A private apt config. It loads after /etc/apt/apt.conf.d, so these settings
# win, and it leaves the runner's own source lists untouched.
setup_apt_config() {
  APT_DIR=$(mktemp -d)
  mkdir -p "$APT_DIR/sources.list.d"
  cat >"$APT_DIR/apt.conf" <<EOF
Dir::Etc::SourceList "/dev/null";
Dir::Etc::SourceParts "$APT_DIR/sources.list.d";
Acquire::Languages "none";
Acquire::IndexTargets::deb::CNF::DefaultEnabled "false";
Acquire::IndexTargets::deb::DEP-11::DefaultEnabled "false";
Acquire::Retries "3";
Acquire::http::Timeout "20";
Acquire::https::Timeout "20";
APT::Get::List-Cleanup "false";
EOF
  export APT_CONFIG="$APT_DIR/apt.conf"
}

use_source() {
  local codename arch
  codename=$(sed -n 's/^VERSION_CODENAME=//p' /etc/os-release)
  arch=$(dpkg --print-architecture)
  cat >"$APT_DIR/sources.list.d/ubuntu.sources" <<EOF
Types: deb
URIs: $1
Suites: $codename $codename-updates $codename-security
Components: main universe
Architectures: $arch
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
  log "apt source: $1"
}

apt_update() {
  sudo rm -rf /var/lib/apt/lists/partial
  timeout -k 10s "$1" sudo APT_CONFIG="$APT_CONFIG" apt-get update
}

switch_to_archive() {
  use_source "$ARCHIVE_URI"
  mirror_switched=true
  apt_update 4m
}

update_package_lists() {
  use_source "$DEFAULT_URI"
  local rc=0
  if [ "$FORCE" = fallback ]; then
    rc=99
  else
    apt_update 3m || rc=$?
  fi
  if [ "$rc" -eq 0 ]; then
    return 0
  fi
  log "apt-get update failed on the default mirror (exit $rc; 124 = timed out)"
  switch_to_archive
}

missing_packages() {
  # Uses $APT_CONFIG (apt-get install -s). Exits 1 when something is missing,
  # and lists the missing packages one per line, indented by two spaces.
  timeout -k 10s 60s npx playwright install-deps --dry-run chromium 2>&1 |
    tee /dev/stderr | sed -n -E 's/^  ([a-z0-9][a-z0-9.+-]*)$/\1/p' || true
}

apt_install() {
  timeout -k 30s 5m sudo APT_CONFIG="$APT_CONFIG" DEBIAN_FRONTEND=noninteractive \
    apt-get install -y --no-install-recommends "$@"
}

install_system_deps() {
  setup_apt_config
  update_package_lists
  local pkgs
  mapfile -t pkgs < <(missing_packages)
  if [ "${#pkgs[@]}" -eq 0 ]; then
    # Chromium did not launch, yet the dry run named nothing to install, or
    # printed something this parser doesn't recognise. More apt would not help.
    log "dry run listed no missing packages; cannot repair the launch failure above"
    return 1
  fi
  log "installing ${#pkgs[@]} package(s): ${pkgs[*]}"
  if apt_install "${pkgs[@]}"; then
    return 0
  fi
  if [ "$mirror_switched" = true ]; then
    return 1
  fi
  log "apt-get install failed or timed out on the default mirror"
  switch_to_archive
  apt_install "${pkgs[@]}"
}

if [ "${CACHE_HIT:-}" = "true" ]; then
  log "browser cache hit"
else
  log "browser cache miss: downloading Chromium"
  timeout -k 30s 5m npx playwright install chromium
fi

if [ -z "$FORCE" ] && smoke_check; then
  echo "::notice title=Playwright browsers::Chromium launched with the runner's libraries (cache-hit=${CACHE_HIT:-false}); apt skipped."
  exit 0
fi

log "Chromium did not launch (or E2E_FORCE_APT=$FORCE); installing system dependencies"
install_system_deps
smoke_check
echo "::notice title=Playwright browsers::Installed system dependencies via apt (cache-hit=${CACHE_HIT:-false}, archive mirror fallback=${mirror_switched})."
