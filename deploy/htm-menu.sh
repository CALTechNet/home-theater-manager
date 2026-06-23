#!/usr/bin/env bash
#
# Home Theater Manager — management CLI.
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

require_root() {
  if [ "$(id -u)" -eq 0 ]; then
    return
  fi

  command -v sudo >/dev/null 2>&1 || { echo "Please run as root (sudo htm)."; exit 1; }
  exec sudo -E "$SCRIPT_PATH" "$@"
}

require() {
  have_tty || { echo "No TTY available; run this in an interactive terminal."; exit 1; }
  require_root "$@"
}

dc() { ( cd "$INSTALL_DIR" && docker compose "$@" ); }

prompt() {
  local label="$1" default="${2:-}" answer
  if [ -n "$default" ]; then
    printf '%s [%s]: ' "$label" "$default" > "$TTY"
  else
    printf '%s: ' "$label" > "$TTY"
  fi
  IFS= read -r answer < "$TTY" || answer=""
  printf '%s' "${answer:-$default}"
}

confirm() {
  local label="$1" default="${2:-y}" answer suffix
  if [ "$default" = "y" ]; then
    suffix="Y/n"
  else
    suffix="y/N"
  fi
  while true; do
    printf '%s [%s]: ' "$label" "$suffix" > "$TTY"
    IFS= read -r answer < "$TTY" || answer=""
    answer="${answer:-$default}"
    case "$answer" in
      y|Y|yes|YES|Yes) return 0 ;;
      n|N|no|NO|No) return 1 ;;
      *) echo "Please answer yes or no." > "$TTY" ;;
    esac
  done
}

pause() {
  echo > "$TTY"
  read -rp "Press Enter to return to the menu..." _ < "$TTY"
}

rediscover() {
  mkdir -p "$INSTALL_DIR/runtime"
  bash "$SCRIPT_DIR/discover.sh" "$INSTALL_DIR/runtime" 2>&1 | tee "$TTY"
  echo "Results saved. Restart the stack to apply hardware-related changes." > "$TTY"
  pause
}

show_hardware() {
  if [ -r "$INSTALL_DIR/runtime/hardware.json" ]; then
    cat "$INSTALL_DIR/runtime/hardware.json" > "$TTY"
  else
    echo "No discovery data yet. Run 'Re-discover hardware' first." > "$TTY"
  fi
  pause
}

install_decklink() {
  local src
  echo "DeckLink driver installer" > "$TTY"
  echo "Leave blank to auto-download Desktop Video from Blackmagic's CDN." > "$TTY"
  echo "You can also paste a signed download link or a local .tar.gz/.deb/.rpm path." > "$TTY"
  src="$(prompt "DeckLink package source" "${HTM_DECKLINK_SRC:-}")"
  echo "Installing DeckLink driver (this may take a few minutes)..." > "$TTY"
  HTM_DECKLINK_SRC="$src" bash "$SCRIPT_DIR/install-decklink.sh" --force || true
  pause
}

choose_connector() {
  local -n _names="$1"
  local choice index
  while true; do
    echo "Available connectors:" > "$TTY"
    for index in "${!_names[@]}"; do
      printf '  %s) %s\n' "$((index + 1))" "${_names[$index]}" > "$TTY"
    done
    echo "  0) Cancel / DeckLink SDI playback" > "$TTY"
    choice="$(prompt "Projector connector" "0")"
    case "$choice" in
      0|"") return 1 ;;
      *[!0-9]*) echo "Please enter a number." > "$TTY" ;;
      *)
        if [ "$choice" -ge 1 ] && [ "$choice" -le "${#_names[@]}" ]; then
          printf '%s' "${_names[$((choice - 1))]}"
          return 0
        fi
        echo "Choose a number from the list." > "$TTY"
        ;;
    esac
  done
}

console_routing() {
  local conns=() name video want_serial=0
  while IFS=$'\t' read -r name _status; do
    [ -n "$name" ] || continue
    conns+=("$name")
  done < <(
    for d in /sys/class/drm/card*-*/; do
      [ -e "$d/status" ] || continue
      n="$(basename "$d")"; n="${n#card*-}"
      printf '%s\t%s\n' "$n" "$(cat "$d/status" 2>/dev/null || echo unknown)"
    done | sort -u
  )

  if [ ${#conns[@]} -eq 0 ]; then
    echo "No GPU display connectors were detected." > "$TTY"
    echo "That is normal for DeckLink-SDI playback; SDI bypasses the Linux console." > "$TTY"
    if confirm "Add a serial console (ttyS0) as a headless fallback?" "n"; then
      bash "$SCRIPT_DIR/console-routing.sh" --serial --apply
    fi
    pause
    return
  fi

  video="$(choose_connector conns)" || video=""
  confirm "Also add a serial console (ttyS0,115200) as a headless recovery fallback?" "n" && want_serial=1

  local -a args=()
  [ -n "$video" ] && args+=(--video-output "$video")
  [ "$want_serial" -eq 1 ] && args+=(--serial)
  if [ ${#args[@]} -eq 0 ]; then
    echo "Nothing selected; no changes made." > "$TTY"
    pause
    return
  fi

  echo "Preview:" > "$TTY"
  bash "$SCRIPT_DIR/console-routing.sh" "${args[@]}" 2>&1 | tee "$TTY"
  if confirm "Apply now? This writes a GRUB drop-in and takes effect after reboot." "n"; then
    bash "$SCRIPT_DIR/console-routing.sh" "${args[@]}" --apply
  fi
  pause
}

reconfigure_ticket_style() {
  local style
  while true; do
    echo "Default ticket style:" > "$TTY"
    echo "  1) receipt  - Thermal receipt (80mm)" > "$TTY"
    echo "  2) fullpage - Full-page color (8.5x11)" > "$TTY"
    style="$(prompt "Choose ticket style" "receipt")"
    case "$style" in
      1|receipt) style="receipt"; break ;;
      2|fullpage) style="fullpage"; break ;;
      *) echo "Please choose 1, 2, receipt, or fullpage." > "$TTY" ;;
    esac
  done
  _set_env HTM_TICKET_STYLE "$style"
  echo "Default style set to '$style'. Choose 'Restart stack' to apply." > "$TTY"
  pause
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

show_menu() {
  cat > "$TTY" <<EOF

Home Theater Manager
Install: $INSTALL_DIR

  1) Re-discover hardware
  2) Show detected hardware
  3) Console / video output routing
  4) Install / update Blackmagic DeckLink driver
  5) Set default ticket style
  6) Show stack status
  7) Tail logs
  8) Restart stack
  9) Start stack
 10) Stop stack
 11) Update app
  0) Exit

EOF
}

main_menu() {
  local choice
  while true; do
    show_menu
    choice="$(prompt "Choose an option" "0")"

    case "$choice" in
      1) rediscover ;;
      2) show_hardware ;;
      3) console_routing ;;
      4) install_decklink ;;
      5) reconfigure_ticket_style ;;
      6) dc ps 2>&1 | tee "$TTY"; pause ;;
      7) echo "Ctrl-C to return to the shell." > "$TTY"; dc logs -f --tail 100 || true; pause ;;
      8) dc up -d --build 2>&1 | tail -20 | tee "$TTY"; pause ;;
      9) dc up -d 2>&1 | tail -20 | tee "$TTY"; pause ;;
      10) dc down 2>&1 | tail -20 | tee "$TTY"; pause ;;
      11) ( cd "$INSTALL_DIR" && git pull && docker compose up -d --build ) 2>&1 | tail -40 | tee "$TTY"; pause ;;
      0|q|quit|exit) break ;;
      *) echo "Unknown option: $choice" > "$TTY"; pause ;;
    esac
  done
}

require "$@"
main_menu
