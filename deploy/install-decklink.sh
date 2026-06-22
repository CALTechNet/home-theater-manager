#!/usr/bin/env bash
#
# Blackmagic Desktop Video (DeckLink) driver installer.
#
# Installs the Desktop Video kernel module (via DKMS) so the DeckLink card can
# output SDI. Blackmagic does NOT provide a public apt/dnf repo or a stable
# direct download URL — the driver lives behind a registration-gated portal — so
# you must point this script at the package, one of:
#
#   HTM_DECKLINK_SRC=/path/to/Desktop_Video_Linux_X.Y.tar.gz   (local file)
#   HTM_DECKLINK_SRC=https://your-lan/desktopvideo.tar.gz       (URL: tar/deb/rpm)
#
# Zero-touch (opt-in) auto-download from Blackmagic's gated API, if you supply
# the per-release download UUID from their support page:
#   HTM_DECKLINK_DOWNLOAD_UUID=<uuid>
#
# Usage:
#   sudo bash install-decklink.sh [--force] [--require]
#     --force    install even if no DeckLink is detected
#     --require  fail (non-zero) instead of skipping when no source is available
#
set -euo pipefail

FORCE=0; REQUIRE=0
for a in "$@"; do
  [ "$a" = "--force" ] && FORCE=1
  [ "$a" = "--require" ] && REQUIRE=1
done

c_b=$'\033[1;34m'; c_g=$'\033[1;32m'; c_y=$'\033[1;33m'; c_r=$'\033[1;31m'; c_x=$'\033[0m'
log()  { printf '%s==>%s %s\n' "$c_b" "$c_x" "$*"; }
ok()   { printf '%s ok %s %s\n' "$c_g" "$c_x" "$*"; }
warn() { printf '%s !! %s %s\n' "$c_y" "$c_x" "$*"; }
die()  { printf '%s xx %s %s\n' "$c_r" "$c_x" "$*" >&2; exit 1; }
skip() { warn "$*"; [ "$REQUIRE" -eq 1 ] && exit 1 || exit 0; }

[ "$(id -u)" -eq 0 ] || die "Run as root (sudo)."

# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}${ID_LIKE:-}" in
  *ubuntu*|*debian*) PKG=apt ;;
  *rhel*|*fedora*|*rocky*|*almalinux*|*centos*) PKG=dnf ;;
  *) die "Unsupported distro for DeckLink install." ;;
esac

# ---------------------------------------------------------------------------
# Detect card / existing driver
# ---------------------------------------------------------------------------
has_card() { command -v lspci >/dev/null 2>&1 && lspci 2>/dev/null | grep -qi blackmagic; }
driver_loaded() { lsmod 2>/dev/null | grep -qi blackmagic || ls /dev/blackmagic* >/dev/null 2>&1; }

if driver_loaded; then
  ok "Blackmagic driver already present (module loaded / /dev/blackmagic exists)."
  [ "$FORCE" -eq 1 ] || exit 0
fi
if ! has_card && [ "$FORCE" -eq 0 ]; then
  skip "No Blackmagic DeckLink detected (use --force to install anyway)."
fi

# ---------------------------------------------------------------------------
# Build prerequisites (DKMS + kernel headers)
# ---------------------------------------------------------------------------
install_prereqs() {
  log "Installing build prerequisites (dkms + kernel headers)..."
  if [ "$PKG" = "apt" ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y dkms build-essential "linux-headers-$(uname -r)" curl tar \
      || apt-get install -y dkms build-essential linux-headers-generic curl tar
  else
    dnf install -y dkms kernel-devel kernel-headers gcc make curl tar \
      || { dnf install -y epel-release || true; dnf install -y dkms kernel-devel kernel-headers gcc make curl tar; }
    if ! ls "/usr/src/kernels/$(uname -r)" >/dev/null 2>&1; then
      warn "kernel-devel for running kernel $(uname -r) not found; DKMS build may require a reboot to matching kernel."
    fi
  fi
}

# ---------------------------------------------------------------------------
# Acquire the Desktop Video package
# ---------------------------------------------------------------------------
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PKG_FILE=""

resolve_gated_url() {
  # Best-effort: POST throwaway registration to Blackmagic's gated API to get the
  # real download URL for a known release UUID. The UUID is per-release and must
  # be supplied by the operator (found on the Desktop Video support page).
  local uuid="$1"
  log "Resolving Blackmagic download URL for UUID $uuid ..."
  curl -fsSL -X POST "https://www.blackmagicdesign.com/api/register/us/download/${uuid}" \
    -H 'Content-Type: application/json;charset=UTF-8' \
    --data "{\"firstname\":\"${HTM_BMD_FIRST:-Home}\",\"lastname\":\"${HTM_BMD_LAST:-Theater}\",\"email\":\"${HTM_BMD_EMAIL:-htm@example.com}\",\"phone\":\"${HTM_BMD_PHONE:-0000000000}\",\"country\":\"us\",\"state\":\"${HTM_BMD_STATE:-CA}\",\"city\":\"${HTM_BMD_CITY:-LA}\",\"product\":\"Desktop Video\"}" \
    2>/dev/null || true
}

acquire() {
  local src="${HTM_DECKLINK_SRC:-}"
  if [ -z "$src" ] && [ -n "${HTM_DECKLINK_DOWNLOAD_UUID:-}" ]; then
    src="$(resolve_gated_url "$HTM_DECKLINK_DOWNLOAD_UUID")"
    [ -n "$src" ] && log "Resolved download URL." || warn "Gated resolution returned nothing."
  fi
  [ -n "$src" ] || skip "No DeckLink package source. Set HTM_DECKLINK_SRC to a local path or URL of the Desktop Video package (download from blackmagicdesign.com/support)."

  if [ -f "$src" ]; then
    PKG_FILE="$src"
    ok "Using local package: $src"
  else
    log "Downloading $src ..."
    PKG_FILE="$WORK/download"
    curl -fSL "$src" -o "$PKG_FILE" || die "Download failed."
    # Name by content type for extension sniffing.
    case "$src" in
      *.deb) mv "$PKG_FILE" "$PKG_FILE.deb"; PKG_FILE="$PKG_FILE.deb" ;;
      *.rpm) mv "$PKG_FILE" "$PKG_FILE.rpm"; PKG_FILE="$PKG_FILE.rpm" ;;
      *)     mv "$PKG_FILE" "$PKG_FILE.tar.gz"; PKG_FILE="$PKG_FILE.tar.gz" ;;
    esac
    ok "Downloaded to $PKG_FILE"
  fi
}

# Find the core (non-GUI) desktopvideo package for this distro+arch.
find_pkg_in_dir() {
  local dir="$1" arch ext sub
  arch="$(uname -m)"; [ "$arch" = "aarch64" ] && arch="arm64"
  if [ "$PKG" = "apt" ]; then ext="deb"; sub="deb"; else ext="rpm"; sub="rpm"; fi
  find "$dir" -type f -ipath "*${sub}*" -iname "desktopvideo[-_]*.${ext}" ! -iname '*gui*' ! -iname '*mediaexpress*' 2>/dev/null | head -1
}

install_pkg_file() {
  local f="$1"
  log "Installing $f ..."
  if [ "$PKG" = "apt" ]; then
    dpkg -i "$f" || apt-get -f install -y
  else
    dnf install -y "$f"
  fi
}

main() {
  install_prereqs
  acquire

  local to_install=""
  case "$PKG_FILE" in
    *.deb|*.rpm) to_install="$PKG_FILE" ;;
    *.tar.gz|*.tgz|*.tar)
      log "Extracting tarball ..."
      mkdir -p "$WORK/x"
      tar -xf "$PKG_FILE" -C "$WORK/x"
      to_install="$(find_pkg_in_dir "$WORK/x")"
      [ -n "$to_install" ] || die "Could not find a desktopvideo .${PKG/dnf/rpm} package inside the tarball."
      ok "Found driver package: $(basename "$to_install")"
      ;;
    *) die "Unknown package format: $PKG_FILE" ;;
  esac

  install_pkg_file "$to_install"

  # DKMS autoinstall is usually triggered by the package; nudge it if needed.
  if command -v dkms >/dev/null 2>&1; then
    dkms autoinstall 2>/dev/null || true
    dkms status 2>/dev/null | grep -i desktopvideo || true
  fi

  modprobe blackmagic 2>/dev/null || true

  if driver_loaded; then
    ok "DeckLink driver installed and loaded."
    command -v BlackmagicFirmwareUpdater >/dev/null 2>&1 && \
      warn "If prompted, run 'BlackmagicFirmwareUpdater status' to check for a card firmware update."
  else
    warn "Driver installed but module not loaded yet. A reboot is often required"
    warn "so DKMS can build against the running kernel. Reboot, then check:"
    warn "  lsmod | grep blackmagic   and   ls /dev/blackmagic*"
  fi
}

main
