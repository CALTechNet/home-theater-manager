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

# Resolve the install directory. This file is usually launched through the
# /usr/local/bin/htm symlink, so follow symlinks before deriving <install>/deploy.
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
INSTALL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "$SOURCE")"
TTY="/dev/tty"

have_tty() { [ -e "$TTY" ] && [ -r "$TTY" ] && [ -w "$TTY" ]; }
ensure_term() {
  if [ -n "${TERM:-}" ] && [ "$TERM" != "dumb" ] &&
     TERM="$TERM" tput clear >/dev/null 2>&1 &&
     TERM="$TERM" tput cup 0 0 >/dev/null 2>&1; then
    return
  fi

  for term in xterm-256color xterm linux vt100; do
    if TERM="$term" tput clear >/dev/null 2>&1 &&
       TERM="$term" tput cup 0 0 >/dev/null 2>&1; then
      export TERM="$term"
      return
    fi
  done

  echo "Terminal '${TERM:-unset}' cannot draw the TUI; set TERM=xterm-256color or run from an SSH/local console terminal."
  exit 1
}
require_root() {
  if [ "$(id -u)" -eq 0 ]; then
    return
  fi

  command -v sudo >/dev/null 2>&1 || { echo "Please run as root (sudo htm)."; exit 1; }
  exec sudo -E "$SCRIPT_PATH" "$@"
}
wt() {
  # Keep the menu UI on /dev/tty while returning menu/form answers to callers.
  # See deploy/install.sh for details on why this redirection order is
  # important for Enter/OK handling when invoked from non-standard stdio.
  whiptail --backtitle "Home Theater Manager" "$@" 3>&1 1>"$TTY" 2>&3 <"$TTY"
}
dc() { ( cd "$INSTALL_DIR" && docker compose "$@" ); }
pause() { wt --title "$1" --msgbox "$2" 20 72; }

require() {
  command -v whiptail >/dev/null 2>&1 || { echo "whiptail not installed."; exit 1; }
  have_tty || { echo "No TTY available; run this in an interactive terminal."; exit 1; }
  command -v tput >/dev/null 2>&1 || { echo "tput not installed."; exit 1; }
  ensure_term
  require_root "$@"
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

console_routing() {
  # Build a connector picker from discovery (or live /sys), then preview/apply.
  local conns=() name status line
  while IFS=$'\t' read -r name status; do
    [ -n "$name" ] || continue
    conns+=("$name" "$status" "off")
  done < <(
    for d in /sys/class/drm/card*-*/; do
      [ -e "$d/status" ] || continue
      n="$(basename "$d")"; n="${n#card*-}"
      printf '%s\t%s\n' "$n" "$(cat "$d/status" 2>/dev/null || echo unknown)"
    done | sort -u
  )

  if [ ${#conns[@]} -eq 0 ]; then
    if ! wt --title "Console / video routing" --yesno \
      "No GPU display connectors were detected on this box.\n\nThat is normal for DeckLink-SDI playback: SDI never touches the\nLinux console, so the VGA console is already free.\n\nAdd a serial console (ttyS0) as a headless fallback?" 14 70; then
      return
    fi
    clear; bash "$SCRIPT_DIR/console-routing.sh" --serial --apply
    echo; read -rp "Press Enter to return to the menu..." _ < "$TTY"; return
  fi

  local video
  video="$(wt --title "Playback output" --radiolist \
    "Pick the GPU connector that drives the PROJECTOR.\nIt will be kept clear of the Linux text console.\n(Space to select, Enter to confirm. Cancel if playback is DeckLink SDI.)" \
    18 72 8 "${conns[@]}")" || video=""

  local want_serial=0
  wt --title "Serial console" --yesno \
    "Also add a serial console (ttyS0,115200) as a headless\nrecovery fallback, in addition to the physical VGA console?" 10 70 && want_serial=1

  local -a args=()
  [ -n "$video" ] && args+=(--video-output "$video")
  [ "$want_serial" -eq 1 ] && args+=(--serial)
  if [ ${#args[@]} -eq 0 ]; then
    pause "Console / video routing" "Nothing selected — no changes made."
    return
  fi

  local preview
  preview="$(bash "$SCRIPT_DIR/console-routing.sh" "${args[@]}" 2>&1)"
  if wt --title "Apply console routing?" --yesno \
    "$preview\n\nApply now? (writes a GRUB drop-in; takes effect after reboot)" 22 76; then
    clear
    bash "$SCRIPT_DIR/console-routing.sh" "${args[@]}" --apply
    echo; read -rp "Press Enter to return to the menu..." _ < "$TTY"
  fi
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
      console   "Console / video output routing (VGA console + serial)" \
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
      console)  console_routing ;;
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

require "$@"
main_menu
