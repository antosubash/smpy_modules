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
#      - `apt-get update` gets its own short timeout, and any index that fails
#        to download fails it (Error-Mode=any). If it fails, the source moves
#        from the runner's mirror list (Azure first) to archive.ubuntu.com and
#        the update runs once more.
#      - Then install only what `install-deps --dry-run` reports missing, with
#        --no-install-recommends, again under its own timeout. A dry run that
#        names nothing, or an install that fails, also moves to the archive.
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
case $(dpkg --print-architecture) in
  amd64 | i386) ARCHIVE_URI=http://archive.ubuntu.com/ubuntu/ ;;
  *) ARCHIVE_URI=http://ports.ubuntu.com/ubuntu-ports/ ;;
esac
if [ -f /etc/apt/apt-mirrors.txt ]; then
  DEFAULT_URI=mirror+file:/etc/apt/apt-mirrors.txt
else
  DEFAULT_URI=$ARCHIVE_URI
fi
mirror_switched=false
deps_complete=false
pkgs=()

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
  # Error-Mode=any: a single index that fails to download fails the update,
  # instead of a warning and exit 0, so a half-reachable mirror takes the
  # fallback too.
  sudo rm -rf /var/lib/apt/lists/partial
  timeout -k 10s "$1" sudo APT_CONFIG="$APT_CONFIG" \
    apt-get update -o APT::Update::Error-Mode=any
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

# Sets $pkgs to what `install-deps --dry-run` reports missing (uses
# $APT_CONFIG: it runs `apt-get install -s`) and $deps_complete to true when it
# says nothing is. The dry run exits 1 when something is missing, and lists the
# packages one per line, indented by two spaces.
scan_missing() {
  local out
  out=$(timeout -k 10s 60s npx playwright install-deps --dry-run chromium 2>&1) || true
  printf '%s\n' "$out" >&2
  deps_complete=false
  if grep -q 'All system dependencies are installed' <<<"$out"; then
    deps_complete=true
  fi
  mapfile -t pkgs < <(sed -n -E 's/^  ([a-z0-9][a-z0-9.+-]*)$/\1/p' <<<"$out")
}

apt_install() {
  timeout -k 30s 5m sudo APT_CONFIG="$APT_CONFIG" DEBIAN_FRONTEND=noninteractive \
    apt-get install -y --no-install-recommends "$@"
}

install_system_deps() {
  setup_apt_config
  update_package_lists
  scan_missing
  if [ "$deps_complete" = true ]; then
    # Every library is present, so apt has nothing to fix: the first launch
    # failure was something else (or a one-off). Skip apt; the smoke check
    # that follows is the retry, and it fails the step if Chromium still
    # cannot start. This is also what E2E_FORCE_APT=1 does on a healthy image.
    log "dry run reports every system dependency installed; nothing to install"
    return 0
  fi
  if [ "${#pkgs[@]}" -eq 0 ] && [ "$mirror_switched" = false ]; then
    # Chromium did not launch, yet the dry run named nothing to install. With
    # no usable package lists it cannot resolve anything, so try the archive.
    log "dry run listed no missing packages on the default mirror"
    switch_to_archive
    scan_missing
    [ "$deps_complete" = true ] && return 0
  fi
  if [ "${#pkgs[@]}" -eq 0 ]; then
    # Still nothing, or output this parser doesn't recognise. More apt would
    # not help; fail rather than leave Chromium broken.
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
  # A timeout can land mid-dpkg; finish any half-configured packages first.
  timeout -k 10s 3m sudo dpkg --configure -a || true
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
if ! smoke_check; then
  echo "::error title=Playwright browsers::Chromium still cannot launch after installing system dependencies (archive mirror fallback=${mirror_switched})."
  exit 1
fi
echo "::notice title=Playwright browsers::Installed system dependencies via apt (cache-hit=${CACHE_HIT:-false}, archive mirror fallback=${mirror_switched})."
