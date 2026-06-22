#!/usr/bin/env bash
#
# Console / video output routing for Home Theater Manager.
#
# A playback box has two independent "output" worlds that are easy to conflate:
#
#   * The Linux *console* (the VGA/HDMI text console + getty you see when you
#     plug a monitor and keyboard into the server for local admin). It is owned
#     by the kernel framebuffer console (fbcon) and is steered by the kernel
#     command line (console=, video=).
#   * The *playback* video that goes to the projector. That is either a
#     Blackmagic DeckLink SDI card (which bypasses the Linux console entirely)
#     or a GPU HDMI/DP connector driven directly by the playback process.
#
# This script lets you decide which GPU connector(s) are dedicated to playback
# (and therefore kept clear of the text console) and which connector keeps the
# VGA console, optionally adding a serial console as a headless fallback. It
# writes a GRUB drop-in / kernel command line accordingly and regenerates GRUB.
#
# DeckLink SDI playback needs nothing here: SDI never touches the framebuffer,
# so every GPU connector is already free for the console. Use this script when a
# GPU connector drives the projector, or to pin the console to a specific output.
#
# Usage:
#   console-routing.sh [--list]                 show connectors/serial, do nothing
#   console-routing.sh --video-output HDMI-A-1 [--video-output DP-1] \
#                      [--console-output VGA-1] [--serial[=ttyS0,115200n8]] \
#                      [--serial-primary] [--no-physical] [--apply]
#   console-routing.sh --revert [--apply]       remove HTM-managed console config
#
# Without --apply the script only PREVIEWS the kernel command line it would set;
# nothing is written and GRUB is not touched. Re-run with --apply to commit, then
# reboot for the change to take effect.
#
set -euo pipefail

MARKER="Home Theater Manager console-routing"
DEB_DROPIN="/etc/default/grub.d/99-htm-console.cfg"
GRUB_DEFAULT="/etc/default/grub"

c_grn=$'\e[32m'; c_yel=$'\e[33m'; c_red=$'\e[31m'; c_off=$'\e[0m'
[ -t 1 ] || { c_grn=""; c_yel=""; c_red=""; c_off=""; }
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s%s%s\n' "$c_grn" "$*" "$c_off"; }
warn() { printf '%s%s%s\n' "$c_yel" "$*" "$c_off" >&2; }
die()  { printf '%s%s%s\n' "$c_red" "$*" "$c_off" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- options ---------------------------------------------------------------
declare -a VIDEO_OUTS=()
CONSOLE_OUT=""
SERIAL=""                 # e.g. ttyS0,115200n8 ; empty = no serial console
SERIAL_PRIMARY=0
PHYSICAL=1                # keep a console on tty0 (the VGA/HDMI text console)
APPLY=0
ACTION="configure"        # configure | list | revert

while [ $# -gt 0 ]; do
  case "$1" in
    --list)            ACTION="list" ;;
    --revert)          ACTION="revert" ;;
    --apply)           APPLY=1 ;;
    --video-output)    shift; [ $# -gt 0 ] || die "--video-output needs a connector name"; VIDEO_OUTS+=("$1") ;;
    --video-output=*)  VIDEO_OUTS+=("${1#*=}") ;;
    --console-output)  shift; [ $# -gt 0 ] || die "--console-output needs a connector name"; CONSOLE_OUT="$1" ;;
    --console-output=*) CONSOLE_OUT="${1#*=}" ;;
    --serial)          SERIAL="ttyS0,115200n8" ;;
    --serial=*)        SERIAL="${1#*=}" ;;
    --serial-primary)  SERIAL_PRIMARY=1 ;;
    --no-physical)     PHYSICAL=0 ;;
    -h|--help)         sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)                 die "Unknown argument: $1 (try --help)" ;;
  esac
  shift
done

# --- hardware enumeration --------------------------------------------------
# DRM connectors live at /sys/class/drm/cardN-<CONNECTOR>/. The <CONNECTOR>
# part (e.g. HDMI-A-1, DP-1, VGA-1, eDP-1) is exactly the name the kernel
# 'video=' parameter expects.
list_connectors() {
  local d name status
  for d in /sys/class/drm/card*-*/; do
    [ -e "$d/status" ] || continue
    name="$(basename "$d")"; name="${name#card*-}"
    status="$(cat "$d/status" 2>/dev/null || echo unknown)"
    printf '%s\t%s\n' "$name" "$status"
  done | sort -u
}

# Real (non-"unknown") serial UARTs from /proc/tty/driver/serial.
list_serial() {
  [ -r /proc/tty/driver/serial ] || return 0
  while IFS= read -r line; do
    case "$line" in
      [0-9]*:\ uart:* )
        echo "$line" | grep -q 'uart:unknown' && continue
        printf 'ttyS%s\n' "${line%%:*}" ;;
    esac
  done < /proc/tty/driver/serial
}

print_inventory() {
  say "GPU display connectors (use the left-hand name for --video-output / --console-output):"
  local any=0
  while IFS=$'\t' read -r name status; do
    any=1
    if [ "$status" = "connected" ]; then
      printf '  %s%-12s%s connected\n' "$c_grn" "$name" "$c_off"
    else
      printf '  %-12s %s\n' "$name" "$status"
    fi
  done < <(list_connectors)
  [ "$any" -eq 1 ] || say "  (none found — no DRM-capable GPU, or running without /sys access)"

  say ""
  say "Serial ports (usable for --serial):"
  local serial; serial="$(list_serial)"
  if [ -n "$serial" ]; then
    printf '  %s\n' $serial
  else
    say "  (none with a real UART detected)"
  fi
}

# --- kernel command line assembly -----------------------------------------
# Build the space-separated parameters HTM manages. We disable each playback
# connector from the kernel console (video=<conn>:d) so the text console never
# lands on the projector, then place console= entries. The LAST console= on the
# command line becomes the primary /dev/console (boot messages + emergency
# shell); systemd spawns a login getty on every console listed.
build_params() {
  local -a parts=()
  local v
  for v in "${VIDEO_OUTS[@]:-}"; do
    [ -n "$v" ] || continue
    parts+=("video=${v}:d")
  done

  # Order console= so the desired primary is last.
  local -a cons=()
  if [ "$SERIAL_PRIMARY" -eq 1 ]; then
    [ "$PHYSICAL" -eq 1 ] && cons+=("console=tty0")
    [ -n "$SERIAL" ]      && cons+=("console=${SERIAL}")
  else
    [ -n "$SERIAL" ]      && cons+=("console=${SERIAL}")
    [ "$PHYSICAL" -eq 1 ] && cons+=("console=tty0")
  fi
  parts+=("${cons[@]:-}")

  # Emit, trimming any empty tokens.
  local out="" p
  for p in "${parts[@]:-}"; do [ -n "$p" ] && out="$out $p"; done
  echo "${out# }"
}

# --- GRUB plumbing ---------------------------------------------------------
regenerate_grub() {
  if have update-grub; then
    update-grub
  elif have grub2-mkconfig; then
    local cfg
    for cfg in /boot/grub2/grub.cfg /boot/efi/EFI/*/grub.cfg; do
      [ -e "$cfg" ] && grub2-mkconfig -o "$cfg"
    done
  else
    warn "Neither update-grub nor grub2-mkconfig found; regenerate GRUB manually."
    return 1
  fi
}

write_debian_dropin() {   # Ubuntu/Debian: /etc/default/grub.d drop-in
  local params="$1"
  mkdir -p "$(dirname "$DEB_DROPIN")"
  cat > "$DEB_DROPIN" <<EOF
# $MARKER — managed file, edit via deploy/console-routing.sh.
# Appends console/video routing to the kernel command line.
GRUB_CMDLINE_LINUX="\$GRUB_CMDLINE_LINUX $params"
EOF
  ok "Wrote $DEB_DROPIN"
}

# RHEL/Rocky have no /etc/default/grub.d; manage a marked GRUB_CMDLINE_LINUX
# token block in /etc/default/grub and let grubby update existing boot entries.
write_rhel_cmdline() {
  local params="$1"
  touch "$GRUB_DEFAULT"
  # Strip any previously managed tokens, then append fresh ones, marked so we
  # can find and remove them on --revert.
  local begin="### BEGIN $MARKER ###" end="### END $MARKER ###"
  # Remove an old managed block (if any).
  sed -i "/$begin/,/$end/d" "$GRUB_DEFAULT" 2>/dev/null || true
  {
    echo "$begin"
    echo "# Managed by deploy/console-routing.sh. Do not edit between these markers."
    echo "GRUB_CMDLINE_LINUX=\"\${GRUB_CMDLINE_LINUX:-} $params\""
    echo "$end"
  } >> "$GRUB_DEFAULT"
  ok "Updated $GRUB_DEFAULT (managed block)"
  if have grubby; then
    grubby --update-kernel=ALL --args="$params" || warn "grubby update failed; new params apply after next kernel build."
  fi
}

revert_config() {
  local changed=0
  if [ -e "$DEB_DROPIN" ]; then
    rm -f "$DEB_DROPIN"; ok "Removed $DEB_DROPIN"; changed=1
  fi
  if [ -e "$GRUB_DEFAULT" ] && grep -q "$MARKER" "$GRUB_DEFAULT" 2>/dev/null; then
    sed -i "/### BEGIN $MARKER ###/,/### END $MARKER ###/d" "$GRUB_DEFAULT"
    ok "Cleaned managed block from $GRUB_DEFAULT"; changed=1
  fi
  if have grubby; then
    # Best-effort: strip our token classes from live entries.
    grubby --update-kernel=ALL --remove-args="console=tty0 console=ttyS0,115200n8" 2>/dev/null || true
  fi
  [ "$changed" -eq 1 ] || warn "No HTM-managed console config found."
}

apply_config() {
  local params="$1"
  [ "$(id -u)" -eq 0 ] || die "Applying GRUB changes needs root. Re-run with sudo."
  if have update-grub; then
    write_debian_dropin "$params"
  else
    write_rhel_cmdline "$params"
  fi
  regenerate_grub
  ok "Console routing applied. Reboot for the new console/video layout to take effect."
}

# --- main ------------------------------------------------------------------
case "$ACTION" in
  list)
    print_inventory
    exit 0
    ;;
  revert)
    print_inventory
    say ""
    if [ "$APPLY" -eq 1 ]; then
      [ "$(id -u)" -eq 0 ] || die "--revert --apply needs root. Re-run with sudo."
      revert_config
      regenerate_grub
      ok "Reverted. Reboot to restore the default console layout."
    else
      say "${c_yel}Preview:${c_off} would remove HTM-managed console config and regenerate GRUB."
      say "Re-run with ${c_grn}--revert --apply${c_off} (as root) to commit."
    fi
    exit 0
    ;;
esac

# configure
if [ ${#VIDEO_OUTS[@]} -eq 0 ] && [ -z "$SERIAL" ] && [ "$PHYSICAL" -eq 1 ] && [ -z "$CONSOLE_OUT" ]; then
  # Nothing meaningful requested: behave like --list to orient the user.
  print_inventory
  say ""
  say "No routing requested. Examples:"
  say "  ${c_grn}console-routing.sh --video-output HDMI-A-1 --console-output VGA-1${c_off}   # GPU drives projector, VGA keeps console"
  say "  ${c_grn}console-routing.sh --video-output HDMI-A-1 --serial --apply${c_off}          # + serial fallback, commit"
  say "  ${c_grn}console-routing.sh --serial --apply${c_off}                                  # DeckLink SDI playback, add serial console"
  exit 0
fi

# Validate the console connector isn't also flagged as a video output.
if [ -n "$CONSOLE_OUT" ]; then
  for v in "${VIDEO_OUTS[@]:-}"; do
    [ "$v" = "$CONSOLE_OUT" ] && die "$CONSOLE_OUT is listed as BOTH a video output and the console output."
  done
fi

PARAMS="$(build_params)"
[ -n "$PARAMS" ] || die "Nothing to set (no video outputs and no console selected)."

say "Planned kernel command-line additions:"
say "  ${c_grn}${PARAMS}${c_off}"
say ""
if [ ${#VIDEO_OUTS[@]} -gt 0 ]; then
  say "  • Playback connector(s) ${VIDEO_OUTS[*]} are disabled from the Linux console (kept clear for the projector)."
fi
[ -n "$CONSOLE_OUT" ] && say "  • VGA/text console stays on ${CONSOLE_OUT}."
[ "$PHYSICAL" -eq 1 ] && say "  • Physical text console (tty0) enabled."
[ -n "$SERIAL" ]      && say "  • Serial console on ${SERIAL}$( [ "$SERIAL_PRIMARY" -eq 1 ] && echo ' (primary)' )."
say ""

if [ "$APPLY" -eq 1 ]; then
  apply_config "$PARAMS"
else
  say "${c_yel}Preview only — nothing written.${c_off} Re-run with ${c_grn}--apply${c_off} (as root) to commit, then reboot."
fi
