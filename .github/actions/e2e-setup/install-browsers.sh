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
#   3. Otherwise: `apt-get update` under its own short timeout. If that fails,
#      drop the Azure mirror for archive.ubuntu.com and try once more. Then
#      install only what `install-deps --dry-run` reports missing, with
#      --no-install-recommends, again under its own timeout.
#   4. Smoke check again. A failure here fails the step.
#
# Worst case adds up to under the 20 minutes the caller wraps this in.
# Every path prints a `::notice::`, so the job summary shows which one ran.
set -euo pipefail

APT_OPTS=(-o Acquire::Retries=3 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20)
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

apt_update() {
  local limit=$1
  sudo rm -rf /var/lib/apt/lists/partial
  timeout -k 10s "$limit" sudo apt-get update "${APT_OPTS[@]}"
}

# The runner sources Ubuntu through `mirror+file:/etc/apt/apt-mirrors.txt`,
# with azure.archive.ubuntu.com listed first. Point every Ubuntu source
# straight at archive.ubuntu.com instead. That host serves -security too.
use_archive_mirror() {
  log "switching apt sources from the Azure mirror to archive.ubuntu.com"
  local f
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    [ -f "$f" ] || continue
    sudo sed -i -E \
      -e 's#mirror\+file:/etc/apt/apt-mirrors\.txt/?#http://archive.ubuntu.com/ubuntu/#g' \
      -e 's#https?://azure\.archive\.ubuntu\.com/ubuntu/?#http://archive.ubuntu.com/ubuntu/#g' \
      "$f"
  done
  mirror_switched=true
}

update_package_lists() {
  local rc=0
  apt_update 2m || rc=$?
  if [ "$rc" -eq 0 ]; then
    return 0
  fi
  log "apt-get update failed on the default mirror (exit $rc; 124 = timed out)"
  use_archive_mirror
  apt_update 3m
}

missing_packages() {
  # Exits 1 when something is missing; its list lines are indented by two spaces.
  timeout -k 10s 60s npx playwright install-deps --dry-run chromium 2>&1 |
    sed -n -E 's/^  ([a-z0-9][a-z0-9.+-]*)$/\1/p' || true
}

apt_install() {
  timeout -k 30s 5m sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --no-install-recommends "${APT_OPTS[@]}" "$@"
}

install_system_deps() {
  update_package_lists
  local pkgs
  mapfile -t pkgs < <(missing_packages)
  if [ "${#pkgs[@]}" -eq 0 ]; then
    # The smoke check failed, but the dry run sees nothing missing (or printed
    # a format this parser doesn't know). Fall back to Playwright's own
    # installer. It repeats `apt-get update`, so it gets a bound too.
    log "dry run listed no packages; running playwright install-deps"
    timeout -k 30s 6m npx playwright install-deps chromium
    return
  fi
  log "installing ${#pkgs[@]} package(s): ${pkgs[*]}"
  if apt_install "${pkgs[@]}"; then
    return 0
  fi
  if [ "$mirror_switched" = true ]; then
    return 1
  fi
  log "apt-get install failed or timed out on the default mirror"
  use_archive_mirror
  apt_update 3m
  apt_install "${pkgs[@]}"
}

if [ "${CACHE_HIT:-}" = "true" ]; then
  log "browser cache hit"
else
  log "browser cache miss: downloading Chromium"
  timeout -k 30s 5m npx playwright install chromium
fi

if smoke_check; then
  echo "::notice title=Playwright browsers::Chromium launched with the runner's libraries (cache-hit=${CACHE_HIT:-false}); apt skipped."
  exit 0
fi

log "Chromium did not launch; installing system dependencies"
install_system_deps
smoke_check
echo "::notice title=Playwright browsers::Installed system dependencies via apt (cache-hit=${CACHE_HIT:-false}, archive mirror fallback=${mirror_switched})."
