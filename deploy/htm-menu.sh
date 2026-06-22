#!/usr/bin/env bash
#
# Home Theater Manager — management TUI.
#
# Installed as `htm` by the installer. Re-run it any time to re-discover
# hardware (after swapping a GPU, DeckLink, or printer), reconfigure outputs,
# or control the stack.
#
#   sudo htm
#
set -euo pipefail

# Resolve the install directory (this script lives in <install>/deploy/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TTY="/dev/tty"

have_tty() { [ -e "$TTY" ] && [ -r "$TTY" ]; }
wt() { whiptail --backtitle "Home Theater Manager" "$@" 3>&1 1>&2 2>&3 < "$TTY" > "$TTY"; }
dc() { ( cd "$INSTALL_DIR" && docker compose "$@" ); }
pause() { wt --title "$1" --msgbox "$2" 20 72; }

require() {
  command -v whiptail >/dev/null 2>&1 || { echo "whiptail not installed."; exit 1; }
  have_tty || { echo "No TTY available; run this in an interactive terminal."; exit 1; }
}

rediscover() {
  local out
  mkdir -p "$INSTALL_DIR/runtime"
  out="$(bash "$SCRIPT_DIR/discover.sh" "$INSTALL_DIR/runtime" 2>&1)"
  pause "Hardware discovery" "$out\n\nResults saved. Restart the stack to apply hardware-related changes."
}

show_hardware() {
  if [ -r "$INSTALL_DIR/runtime/hardware.json" ]; then
    pause "Detected hardware" "$(cat "$INSTALL_DIR/runtime/hardware.json")"
  else
    pause "Detected hardware" "No discovery data yet. Run 'Re-discover hardware' first."
  fi
}

install_decklink() {
  local src
  src="$(wt --title "DeckLink driver" --inputbox \
    "Leave BLANK to auto-download Desktop Video from Blackmagic's CDN.\n\nOr paste a signed download link (ends with '?verify=...') from\nblackmagicdesign.com/support, or a local .tar.gz/.deb/.rpm path,\nif the automatic download is refused." 14 72 "${HTM_DECKLINK_SRC:-}")" || return
  clear
  echo "Installing DeckLink driver (this may take a few minutes)..."
  HTM_DECKLINK_SRC="$src" bash "$SCRIPT_DIR/install-decklink.sh" --force || true
  echo; read -rp "Press Enter to return to the menu..." _ < "$TTY"
}

reconfigure_ticket_style() {
  local style
  style="$(wt --title "Default ticket style" --menu \
    "Tickets are generated as PDFs printed from your workstation.\nDefault style (changeable per print in the UI):" 14 64 2 \
    receipt "Thermal receipt (80mm)" \
    fullpage "Full-page color (8.5x11)")" || return
  _set_env HTM_TICKET_STYLE "$style"
  pause "Tickets" "Default style set to '$style'. Choose 'Restart stack' to apply."
}

# Upsert KEY=VALUE in the .env file.
_set_env() {
  local key="$1" val="$2" file="$INSTALL_DIR/.env"
  touch "$file"
  if grep -q "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$file"
  else
    echo "${key}=${val}" >> "$file"
  fi
}

main_menu() {
  while true; do
    local choice
    choice="$(wt --title "Main menu" --menu "Install: $INSTALL_DIR" 20 70 10 \
      discover  "Re-discover hardware (GPU/DeckLink/printer/audio)" \
      hardware  "Show detected hardware" \
      decklink  "Install / update Blackmagic DeckLink driver" \
      tickets   "Set default ticket style (receipt / full-page)" \
      status    "Show stack status" \
      logs      "Tail logs" \
      restart   "Restart stack" \
      start     "Start stack" \
      stop      "Stop stack" \
      update    "Update app (git pull + rebuild)" \
      quit      "Exit")" || break

    case "$choice" in
      discover) rediscover ;;
      hardware) show_hardware ;;
      decklink) install_decklink ;;
      tickets)  reconfigure_ticket_style ;;
      status)   pause "Status" "$(dc ps 2>&1)" ;;
      logs)     clear; echo "Ctrl-C to return to menu."; dc logs -f --tail 100 || true ;;
      restart)  pause "Restart" "$(dc up -d --build 2>&1 | tail -20)" ;;
      start)    pause "Start" "$(dc up -d 2>&1 | tail -20)" ;;
      stop)     pause "Stop" "$(dc down 2>&1 | tail -20)" ;;
      update)
        local out
        out="$(cd "$INSTALL_DIR" && git pull 2>&1 && docker compose up -d --build 2>&1 | tail -20)"
        pause "Update" "$out" ;;
      quit) break ;;
    esac
  done
  clear
}

require
main_menu
