#!/usr/bin/env bash
#
# Hardware auto-discovery for Home Theater Manager.
#
# Detects GPUs (NVIDIA / AMD / Intel, discrete and integrated), Blackmagic
# DeckLink cards, USB thermal printers, and audio outputs. Writes:
#   <outdir>/hardware.json   machine-readable, mounted into the backend for the UI
#   <outdir>/hardware.env    HTM_* hints sourced by the installer
# and prints a human-readable summary.
#
# Usage: discover.sh [OUTDIR] [--quiet]
#
set -euo pipefail

OUTDIR="${1:-.}"
QUIET=0
for a in "$@"; do [ "$a" = "--quiet" ] && QUIET=1; done
[ -d "$OUTDIR" ] || OUTDIR="."

say() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }
json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# GPUs
# ---------------------------------------------------------------------------
gpu_objs=()
primary_vendor=""
primary_hwaccel=""

classify_gpu() {
  # $1 vendor id (hex, lowercase)
  case "$1" in
    10de) echo "NVIDIA discrete nvdec" ;;
    1002) echo "AMD amd vaapi" ;;       # APU or discrete; VAAPI for decode
    8086) echo "Intel integrated qsv" ;;
    *)    echo "Unknown other none" ;;
  esac
}

discover_gpus() {
  have lspci || { say "  (lspci not available — install pciutils for GPU detection)"; return; }
  local has_dri="false"
  ls /dev/dri/renderD* >/dev/null 2>&1 && has_dri="true"

  while IFS= read -r line; do
    # Only display-class devices.
    echo "$line" | grep -Eqi 'VGA compatible controller|3D controller|Display controller' || continue
    local pci vid model rest meta vendor kind decode
    pci="${line%% *}"
    vid="$(echo "$line" | grep -oiE '\[[0-9a-f]{4}:[0-9a-f]{4}\]' | head -1 | tr -d '[]' | cut -d: -f1 | tr 'A-F' 'a-f')"
    model="$(echo "$line" | sed -E 's/^[^:]+: //; s/ \[[0-9a-f]{4}:[0-9a-f]{4}\].*$//')"
    meta="$(classify_gpu "$vid")"
    vendor="$(echo "$meta" | awk '{print $1}')"
    kind="$(echo "$meta" | awk '{print $2}')"
    decode="$(echo "$meta" | awk '{print $3}')"

    # NVIDIA: prefer nvdec only if the driver is present, else fall back.
    if [ "$vid" = "10de" ] && ! have nvidia-smi; then
      decode="nvdec"   # still report intent; driver install is a Phase 3 prereq
    fi

    gpu_objs+=("{\"vendor\":\"$vendor\",\"model\":\"$(json_escape "$model")\",\"pci\":\"$pci\",\"kind\":\"$kind\",\"decode\":\"$decode\",\"vaapi\":$has_dri}")
    say "  GPU: $vendor $model ($kind, decode=$decode)"

    # Choose a primary: first discrete wins, else first integrated.
    if [ -z "$primary_vendor" ] || { [ "$kind" = "discrete" ] && [ "$primary_hwaccel" = "qsv" ]; }; then
      primary_vendor="$vendor"
      primary_hwaccel="$decode"
    fi
  done < <(lspci -nn 2>/dev/null)

  if [ ${#gpu_objs[@]} -eq 0 ]; then
    say "  No GPUs detected."
  fi
}

# ---------------------------------------------------------------------------
# Display connectors (DRM) + serial ports — for console/video output routing.
# See deploy/console-routing.sh. The connector name (e.g. HDMI-A-1) is exactly
# what the kernel 'video=' parameter expects.
# ---------------------------------------------------------------------------
connector_objs=()
serial_objs=()
discover_outputs() {
  local d name status
  local base card device
  for d in /sys/class/drm/card*-*/; do
    [ -e "$d/status" ] || continue
    base="$(basename "$d")"          # e.g. card1-DP-1
    card="${base%%-*}"               # card1
    name="${base#*-}"                # DP-1  (connector name for video=/mpv)
    device="/dev/dri/${card}"        # KMS node mpv --drm-device targets
    status="$(cat "$d/status" 2>/dev/null || echo unknown)"
    connector_objs+=("{\"name\":\"$(json_escape "$name")\",\"status\":\"$(json_escape "$status")\",\"card\":\"$(json_escape "$card")\",\"device\":\"$(json_escape "$device")\"}")
    say "  Connector: $name ($status) [$device]"
  done
  if [ ${#connector_objs[@]} -eq 0 ]; then
    say "  No DRM display connectors enumerated."
  fi

  if [ -r /proc/tty/driver/serial ]; then
    while IFS= read -r line; do
      case "$line" in
        [0-9]*:\ uart:*)
          echo "$line" | grep -q 'uart:unknown' && continue
          local port="ttyS${line%%:*}"
          serial_objs+=("{\"port\":\"$port\"}")
          say "  Serial: $port" ;;
      esac
    done < /proc/tty/driver/serial
  fi
  if [ ${#serial_objs[@]} -eq 0 ]; then
    say "  No usable serial UART detected."
  fi
}

# ---------------------------------------------------------------------------
# Blackmagic DeckLink (SDI)
# ---------------------------------------------------------------------------
decklink_objs=()
has_decklink="false"
discover_decklink() {
  if have lspci && lspci -nn 2>/dev/null | grep -qi 'blackmagic'; then
    while IFS= read -r line; do
      local model; model="$(echo "$line" | sed -E 's/^[^:]+: //')"
      decklink_objs+=("{\"model\":\"$(json_escape "$model")\",\"present\":true}")
      say "  DeckLink: $model"
      has_decklink="true"
    done < <(lspci -nn 2>/dev/null | grep -i 'blackmagic')
  fi
  if ls /dev/blackmagic* >/dev/null 2>&1; then
    has_decklink="true"
    say "  DeckLink driver devices present (/dev/blackmagic*)"
  fi
  if [ "$has_decklink" = "false" ]; then
    say "  No Blackmagic DeckLink detected."
  fi
}

# ---------------------------------------------------------------------------
# Thermal printers (USB)
# ---------------------------------------------------------------------------
printer_objs=()
discover_printers() {
  have lsusb || { say "  (lsusb not available — install usbutils for printer detection)"; return; }
  # vendor id -> friendly name for common ESC/POS thermal printers.
  declare -A vendors=( [04b8]="Epson" [0519]="Star Micronics" [1504]="Bixolon" [1d90]="Citizen" [0dd4]="Custom/Partner" )
  local found=0
  while IFS= read -r line; do
    local ids vid pid name
    ids="$(echo "$line" | grep -oE 'ID [0-9a-f]{4}:[0-9a-f]{4}' | awk '{print $2}')"
    [ -z "$ids" ] && continue
    vid="${ids%%:*}"; pid="${ids##*:}"
    if [ -n "${vendors[$vid]:-}" ]; then
      name="$(echo "$line" | sed -E 's/.*ID [0-9a-f]{4}:[0-9a-f]{4} //')"
      printer_objs+=("{\"vendor\":\"${vendors[$vid]}\",\"name\":\"$(json_escape "$name")\",\"usb_vendor\":\"0x$vid\",\"usb_product\":\"0x$pid\"}")
      say "  Printer: ${vendors[$vid]} — $name (0x$vid:0x$pid)"
      found=1
    fi
  done < <(lsusb 2>/dev/null)
  if [ "$found" -eq 0 ]; then
    say "  No USB thermal printer detected (network printers are configured by IP)."
  fi
}

# ---------------------------------------------------------------------------
# Audio outputs
# ---------------------------------------------------------------------------
audio_objs=()
discover_audio() {
  if [ -r /proc/asound/cards ]; then
    while IFS= read -r line; do
      echo "$line" | grep -qE '^[ ]*[0-9]+ ' || continue
      local idx name
      idx="$(echo "$line" | awk '{print $1}')"
      name="$(echo "$line" | sed -E 's/^[ ]*[0-9]+ \[[^]]*\]: //')"
      audio_objs+=("{\"index\":$idx,\"name\":\"$(json_escape "$name")\"}")
      say "  Audio: card $idx — $name"
    done < /proc/asound/cards
  fi
  if [ ${#audio_objs[@]} -eq 0 ]; then
    say "  No ALSA audio cards enumerated."
  fi
}

join_objs() { local IFS=,; echo "$*"; }

main() {
  say "Discovering hardware..."
  say "GPUs:";     discover_gpus
  say "Outputs:";  discover_outputs
  say "Capture:";  discover_decklink
  say "Printers:"; discover_printers
  say "Audio:";    discover_audio

  : "${primary_vendor:=Unknown}"
  : "${primary_hwaccel:=none}"

  cat > "$OUTDIR/hardware.json" <<EOF
{
  "discovered_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "primary_gpu_vendor": "$(json_escape "$primary_vendor")",
  "primary_hwaccel": "$(json_escape "$primary_hwaccel")",
  "has_decklink": $has_decklink,
  "gpus": [ $(join_objs "${gpu_objs[@]:-}") ],
  "connectors": [ $(join_objs "${connector_objs[@]:-}") ],
  "serial": [ $(join_objs "${serial_objs[@]:-}") ],
  "decklink": [ $(join_objs "${decklink_objs[@]:-}") ],
  "printers": [ $(join_objs "${printer_objs[@]:-}") ],
  "audio": [ $(join_objs "${audio_objs[@]:-}") ]
}
EOF

  cat > "$OUTDIR/hardware.env" <<EOF
# Generated by discover.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
HTM_GPU_VENDOR=$primary_vendor
HTM_HWACCEL=$primary_hwaccel
HTM_HAS_DECKLINK=$has_decklink
EOF

  say ""
  say "Wrote $OUTDIR/hardware.json and $OUTDIR/hardware.env"
  say "Primary GPU: $primary_vendor (hwaccel=$primary_hwaccel) · DeckLink: $has_decklink"
}

main
