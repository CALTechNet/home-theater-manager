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
HTM_PRINTER_KIND="${HTM_PRINTER_KIND:-none}"
HTM_PRINTER_HOST="${HTM_PRINTER_HOST:-}"
HTM_PRINTER_PORT="${HTM_PRINTER_PORT:-9100}"
HTM_PRINTER_USB_VENDOR="${HTM_PRINTER_USB_VENDOR:-}"
HTM_PRINTER_USB_PRODUCT="${HTM_PRINTER_USB_PRODUCT:-}"

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
have_tty() { [ -e "$TTY" ] && [ -r "$TTY" ]; }

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
  log "Installing base packages (git, curl, newt)..."
  if [ "$PKG" = "apt" ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y ca-certificates curl git whiptail
  else
    dnf install -y ca-certificates curl git newt
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

# ---------------------------------------------------------------------------
# TUI wizard (whiptail). Falls back to plain prompts without a TTY.
# ---------------------------------------------------------------------------
wt() { whiptail --backtitle "Home Theater Manager Setup" "$@" 3>&1 1>&2 2>&3 < "$TTY" > "$TTY"; }

run_tui() {
  if [ "$USE_TUI" -eq 0 ] || ! have_tty || ! command -v whiptail >/dev/null 2>&1; then
    warn "Running non-interactively; using defaults/env for configuration."
    return
  fi

  wt --title "Welcome" --msgbox \
    "This wizard configures your Home Theater Manager.\n\nYou'll set the theater name, media location, seat grid, and thermal printer.\n\nPress OK to begin." 14 64

  HTM_THEATER_NAME="$(wt --title "Theater name" --inputbox \
    "Name printed on tickets and shown in the UI:" 10 64 "$HTM_THEATER_NAME")"

  HTM_MEDIA_HOST_PATH="$(wt --title "Media location" --inputbox \
    "Host path to your movies/trailers (your NFS/SMB mount).\nMounted read-only into the app." 11 64 "$HTM_MEDIA_HOST_PATH")"

  HTM_SEAT_MAX_ROW="$(wt --title "Seat grid — rows" --inputbox \
    "Last seat row letter (A..?). E.g. F gives rows A-F." 10 64 "$HTM_SEAT_MAX_ROW")"

  HTM_SEAT_MAX_NUMBER="$(wt --title "Seat grid — seats per row" --inputbox \
    "Seats per row (1..N). E.g. 6 gives 1-6." 10 64 "$HTM_SEAT_MAX_NUMBER")"

  HTM_PRINTER_KIND="$(wt --title "Thermal printer" --menu \
    "Select your Epson-style receipt printer connection:" 16 64 4 \
    none    "No printer (render receipts on screen only)" \
    network "Network printer (IP + port 9100)" \
    usb     "USB printer (vendor/product IDs)" \
    file    "Write receipts to files (debugging)" )"

  case "$HTM_PRINTER_KIND" in
    network)
      HTM_PRINTER_HOST="$(wt --title "Printer IP" --inputbox "Printer IP address:" 10 64 "$HTM_PRINTER_HOST")"
      HTM_PRINTER_PORT="$(wt --title "Printer port" --inputbox "Printer TCP port:" 10 64 "$HTM_PRINTER_PORT")"
      ;;
    usb)
      HTM_PRINTER_USB_VENDOR="$(wt --title "USB vendor id" --inputbox "Vendor id in hex (from lsusb), e.g. 0x04b8:" 10 64 "${HTM_PRINTER_USB_VENDOR:-0x04b8}")"
      HTM_PRINTER_USB_PRODUCT="$(wt --title "USB product id" --inputbox "Product id in hex (from lsusb), e.g. 0x0e15:" 10 64 "${HTM_PRINTER_USB_PRODUCT:-0x0e15}")"
      ;;
  esac

  wt --title "Confirm" --yesno \
    "Ready to deploy with:\n\n Theater : $HTM_THEATER_NAME\n Media   : $HTM_MEDIA_HOST_PATH\n Seats   : A-$HTM_SEAT_MAX_ROW x 1-$HTM_SEAT_MAX_NUMBER\n Printer : $HTM_PRINTER_KIND\n\nBuild and start now?" 16 64 \
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
HTM_PRINTER_KIND=${HTM_PRINTER_KIND}
HTM_PRINTER_HOST=${HTM_PRINTER_HOST}
HTM_PRINTER_PORT=${HTM_PRINTER_PORT}
HTM_PRINTER_USB_VENDOR=${HTM_PRINTER_USB_VENDOR}
HTM_PRINTER_USB_PRODUCT=${HTM_PRINTER_USB_PRODUCT}
HTM_PRINTER_FILE_PATH=/data/tickets
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
  run_tui
  write_env
  deploy
  print_done
}

main "$@"
