#!/usr/bin/env bash
#
# Home Theater Manager — one-shot installer + TUI setup wizard.
#
# Usage (interactive TUI):
#   curl -fsSL https://raw.githubusercontent.com/CALTechNet/home-theater-manager/main/deploy/install.sh | sudo bash
#
# Supports: Ubuntu Server (22.04/24.04) and Rocky Linux (9/10).
# It installs Docker + Compose, clones the repo, walks you through a TUI to
# generate .env, then builds and starts the stack.
#
# Non-interactive: set env vars (see "Defaults" below) and add --no-tui:
#   curl -fsSL .../install.sh | sudo HTM_MEDIA_HOST_PATH=/mnt/media bash -s -- --no-tui
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults (overridable by env or the TUI)
# ---------------------------------------------------------------------------
REPO_URL="${HTM_REPO_URL:-https://github.com/CALTechNet/home-theater-manager.git}"
REPO_REF="${HTM_REPO_REF:-main}"
INSTALL_DIR="${HTM_INSTALL_DIR:-/opt/home-theater-manager}"

HTM_THEATER_NAME="${HTM_THEATER_NAME:-Home Cinema}"
HTM_MEDIA_HOST_PATH="${HTM_MEDIA_HOST_PATH:-/mnt/media}"
HTM_SEAT_MAX_ROW="${HTM_SEAT_MAX_ROW:-F}"
HTM_SEAT_MAX_NUMBER="${HTM_SEAT_MAX_NUMBER:-6}"
HTM_TICKET_STYLE="${HTM_TICKET_STYLE:-receipt}"
HTM_DECKLINK_VERSION="${HTM_DECKLINK_VERSION:-16.0}"
export HTM_DECKLINK_VERSION

USE_TUI=1
for arg in "$@"; do
  [ "$arg" = "--no-tui" ] && USE_TUI=0
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
c_blue=$'\033[1;34m'; c_grn=$'\033[1;32m'; c_red=$'\033[1;31m'; c_yel=$'\033[1;33m'; c_off=$'\033[0m'
log()  { printf '%s==>%s %s\n' "$c_blue" "$c_off" "$*"; }
ok()   { printf '%s ok %s %s\n' "$c_grn" "$c_off" "$*"; }
warn() { printf '%s !! %s %s\n' "$c_yel" "$c_off" "$*"; }
die()  { printf '%s xx %s %s\n' "$c_red" "$c_off" "$*" >&2; exit 1; }

# A TTY for interactive prompts even when the script is piped from curl.
TTY="/dev/tty"
have_tty() { [ -e "$TTY" ] && [ -r "$TTY" ] && [ -w "$TTY" ]; }

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    die "Please run as root (pipe to 'sudo bash')."
  fi
}

detect_os() {
  [ -r /etc/os-release ] || die "Cannot detect OS (/etc/os-release missing)."
  # shellcheck disable=SC1091
  . /etc/os-release
  OS_ID="${ID:-}"
  OS_LIKE="${ID_LIKE:-}"
  case "$OS_ID" in
    ubuntu|debian) PKG="apt" ;;
    rocky|rhel|almalinux|centos|fedora) PKG="dnf" ;;
    *)
      case "$OS_LIKE" in
        *debian*) PKG="apt" ;;
        *rhel*|*fedora*) PKG="dnf" ;;
        *) die "Unsupported distro '$OS_ID'. Supported: Ubuntu, Rocky." ;;
      esac
      ;;
  esac
  ok "Detected $PRETTY_NAME (package manager: $PKG)"
}

# ---------------------------------------------------------------------------
# Dependency installation
# ---------------------------------------------------------------------------
install_base() {
  log "Installing base packages (git, curl, newt, pciutils, usbutils)..."
  if [ "$PKG" = "apt" ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y ca-certificates curl git whiptail pciutils usbutils
  else
    dnf install -y ca-certificates curl git newt pciutils usbutils
  fi
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    ok "Docker + Compose already present."
    return
  fi
  log "Installing Docker Engine + Compose plugin..."
  if [ "$PKG" = "apt" ]; then
    install -m 0755 -d /etc/apt/keyrings
    local repo="ubuntu"; [ "$OS_ID" = "debian" ] && repo="debian"
    curl -fsSL "https://download.docker.com/linux/${repo}/gpg" -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    local codename; codename="$(. /etc/os-release; echo "${VERSION_CODENAME:-}")"
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${repo} ${codename} stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    dnf install -y dnf-plugins-core || true
    dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo 2>/dev/null \
      || dnf config-manager addrepo --from-repofile=https://download.docker.com/linux/centos/docker-ce.repo
    dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
  systemctl enable --now docker
  ok "Docker installed."
}

# ---------------------------------------------------------------------------
# Repo
# ---------------------------------------------------------------------------
fetch_repo() {
  if [ -d "$INSTALL_DIR/.git" ]; then
    log "Updating existing checkout at $INSTALL_DIR..."
    git -C "$INSTALL_DIR" fetch --depth 1 origin "$REPO_REF"
    git -C "$INSTALL_DIR" checkout "$REPO_REF"
    git -C "$INSTALL_DIR" reset --hard "origin/$REPO_REF"
  else
    log "Cloning $REPO_URL ($REPO_REF) into $INSTALL_DIR..."
    git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$INSTALL_DIR"
  fi
  ok "Repository ready at $INSTALL_DIR"
}

# Hardware auto-discovery (GPU/DeckLink/printer/audio) -> hardware.json + .env.
run_discovery() {
  log "Auto-discovering connected hardware..."
  mkdir -p "$INSTALL_DIR/runtime"
  bash "$INSTALL_DIR/deploy/discover.sh" "$INSTALL_DIR/runtime" || warn "Discovery had issues; continuing."
  # Pull primary GPU / DeckLink hints into this shell for .env.
  if [ -r "$INSTALL_DIR/runtime/hardware.env" ]; then
    # shellcheck disable=SC1091
    . "$INSTALL_DIR/runtime/hardware.env"
  fi
}

# Offer to install the Blackmagic DeckLink driver when a card is detected but no
# driver is loaded. Blackmagic has no public repo, so we ask for the package.
maybe_install_decklink() {
  [ "${HTM_HAS_DECKLINK:-false}" = "true" ] || return 0
  if lsmod 2>/dev/null | grep -qi blackmagic || ls /dev/blackmagic* >/dev/null 2>&1; then
    ok "DeckLink driver already loaded; skipping driver install."
    return 0
  fi
  if [ "$USE_TUI" -eq 0 ] || ! have_tty; then
    # Non-interactive: attempt install (script auto-tries the pinned CDN version
    # and skips cleanly if it needs a signed token / source).
    export HTM_DECKLINK_SRC="${HTM_DECKLINK_SRC:-}"
    bash "$INSTALL_DIR/deploy/install-decklink.sh" || warn "DeckLink install had issues."
    return 0
  fi

  wt --title "Blackmagic DeckLink" --yesno \
    "A DeckLink card was detected but no driver is loaded.\n\nThe installer will try Blackmagic's CDN for Desktop Video v${HTM_DECKLINK_VERSION:-16.0}\nautomatically. If that needs a signed token, you can paste a download\nlink from blackmagicdesign.com/support instead.\n\nInstall the SDI driver now?" 16 72 || return 0

  HTM_DECKLINK_SRC="$(wt --title "DeckLink package source" --inputbox \
    "Leave BLANK to auto-download Desktop Video v${HTM_DECKLINK_VERSION:-16.0} from Blackmagic's CDN.\n\nOr paste a signed download link (ends with '?verify=...') / local path\nif the automatic download is refused." 13 72 "${HTM_DECKLINK_SRC:-}")" || return 0

  export HTM_DECKLINK_SRC
  bash "$INSTALL_DIR/deploy/install-decklink.sh" || warn "DeckLink install had issues; see output above."
}

# Install a global `htm` command pointing at the management menu.
install_htm_command() {
  ln -sf "$INSTALL_DIR/deploy/htm-menu.sh" /usr/local/bin/htm
  chmod +x "$INSTALL_DIR/deploy/htm-menu.sh" "$INSTALL_DIR/deploy/discover.sh" \
    "$INSTALL_DIR/deploy/install-decklink.sh" 2>/dev/null || true
  ok "Installed 'htm' management command (run: sudo htm)."
}

# ---------------------------------------------------------------------------
# TUI wizard (whiptail). Falls back to plain prompts without a TTY.
# ---------------------------------------------------------------------------
wt() {
  # Keep whiptail's UI attached to the real terminal while still capturing
  # form/menu answers in command substitutions. Redirection order matters:
  # whiptail/newt draws on stdout and emits answers on stderr.
  whiptail --backtitle "Home Theater Manager Setup" "$@" 3>&1 1>"$TTY" 2>&3 <"$TTY"
}


run_tui() {
  if [ "$USE_TUI" -eq 0 ] || ! have_tty || ! command -v whiptail >/dev/null 2>&1; then
    warn "Running non-interactively; using defaults/env for configuration."
    return
  fi

  local intro="This wizard configures your Home Theater Manager."
  if [ -r "$INSTALL_DIR/runtime/hardware.json" ]; then
    intro="$intro\n\nDetected hardware:\n GPU      : ${HTM_GPU_VENDOR:-Unknown} (decode: ${HTM_HWACCEL:-none})\n DeckLink : ${HTM_HAS_DECKLINK:-false}\n\nFull details saved to hardware.json. You can re-run discovery any time with: sudo htm"
  fi

  HTM_THEATER_NAME="$(wt --title "Theater name" --inputbox \
    "$intro\n\nName printed on tickets and shown in the UI:" 18 72 "$HTM_THEATER_NAME")"

  HTM_MEDIA_HOST_PATH="$(wt --title "Media location" --inputbox \
    "Host path to your movies/trailers (your NFS/SMB mount).\nMounted read-only into the app." 11 64 "$HTM_MEDIA_HOST_PATH")"

  HTM_SEAT_MAX_ROW="$(wt --title "Seat grid — rows" --inputbox \
    "Last seat row letter (A..?). E.g. F gives rows A-F." 10 64 "$HTM_SEAT_MAX_ROW")"

  HTM_SEAT_MAX_NUMBER="$(wt --title "Seat grid — seats per row" --inputbox \
    "Seats per row (1..N). E.g. 6 gives 1-6." 10 64 "$HTM_SEAT_MAX_NUMBER")"

  # Tickets are generated as PDFs and printed from the operator's workstation to
  # any printer it can reach. Pick the default style (switchable per-print in UI).
  HTM_TICKET_STYLE="$(wt --title "Default ticket style" --menu \
    "Tickets are generated as PDFs you print from your workstation to any\nprinter (network, USB, thermal, or a normal color printer).\n\nDefault style (changeable per print in the UI):" 18 70 2 \
    receipt  "Thermal receipt (80mm roll)" \
    fullpage "Full-page color ticket (8.5x11)" )"

  wt --title "Confirm" --yesno \
    "Ready to deploy with:\n\n Theater : $HTM_THEATER_NAME\n Media   : $HTM_MEDIA_HOST_PATH\n Seats   : A-$HTM_SEAT_MAX_ROW x 1-$HTM_SEAT_MAX_NUMBER\n GPU     : ${HTM_GPU_VENDOR:-Unknown} / DeckLink ${HTM_HAS_DECKLINK:-false}\n Tickets : $HTM_TICKET_STYLE PDF (printed from your workstation)\n\nBuild and start now?" 18 66 \
    || die "Aborted by user."
}

# ---------------------------------------------------------------------------
# .env generation
# ---------------------------------------------------------------------------
write_env() {
  local env_file="$INSTALL_DIR/.env"
  log "Writing $env_file"
  cat > "$env_file" <<EOF
# Generated by deploy/install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
HTM_DATABASE_URL=sqlite:////data/htm.db
HTM_MEDIA_HOST_PATH=${HTM_MEDIA_HOST_PATH}
HTM_MEDIA_ROOT=/mnt/media
HTM_PLAYBACK_URL=http://playback:9000
HTM_THEATER_NAME=${HTM_THEATER_NAME}
HTM_SEAT_MAX_ROW=${HTM_SEAT_MAX_ROW}
HTM_SEAT_MAX_NUMBER=${HTM_SEAT_MAX_NUMBER}
HTM_TICKET_STYLE=${HTM_TICKET_STYLE:-receipt}
HTM_HARDWARE_FILE=/runtime/hardware.json
# Hardware hints from auto-discovery (informational; consumed by Phase 3 playback)
HTM_GPU_VENDOR=${HTM_GPU_VENDOR:-Unknown}
HTM_HWACCEL=${HTM_HWACCEL:-none}
HTM_HAS_DECKLINK=${HTM_HAS_DECKLINK:-false}
EOF
  # Ensure the media path exists so the read-only mount doesn't fail.
  mkdir -p "$HTM_MEDIA_HOST_PATH" 2>/dev/null || warn "Could not create $HTM_MEDIA_HOST_PATH (mount it before first scan)."
  ok ".env written."
}

# ---------------------------------------------------------------------------
# Build + start
# ---------------------------------------------------------------------------
deploy() {
  log "Building and starting containers (this may take a few minutes)..."
  ( cd "$INSTALL_DIR" && docker compose up -d --build )
  ok "Stack is up."
}

print_done() {
  local ip; ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  cat <<EOF

${c_grn}Home Theater Manager is running.${c_off}

  Open:   https://${ip:-<server-ip>}/
          (self-signed TLS — your browser will warn once; accept it)

  Manage: cd $INSTALL_DIR
          docker compose ps        # status
          docker compose logs -f   # logs
          docker compose down      # stop

  Config: $INSTALL_DIR/.env   (re-run installer or edit, then 'docker compose up -d')

  Manage: sudo htm   (TUI: re-discover hardware, console/video routing, logs, update)

Console: this is a server OS. If a GPU connector drives the projector, route the
VGA text console to a different output (and optionally add a serial console):
  sudo bash $INSTALL_DIR/deploy/console-routing.sh --list
DeckLink SDI playback needs nothing here — SDI leaves the VGA console free.

Printing: tickets print from the workstation/browser — pick any printer it can
reach (network, USB, thermal, or a normal 8.5x11 color printer) in the print
dialog. The server only outputs to the projector + audio.

Next: open the Media tab and click "Scan library" to index your files.
NOTE: Phase 1 uses a MOCK playback engine. Real GPU/DeckLink output is Phase 3.
EOF
}

main() {
  require_root
  detect_os
  install_base
  install_docker
  fetch_repo
  run_discovery
  install_htm_command
  run_tui
  maybe_install_decklink
  write_env
  deploy
  print_done
}

main "$@"
