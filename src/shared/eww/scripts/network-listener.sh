#!/bin/bash
# EWW network listener -- event-driven via nmcli monitor
# Output: single-line JSON with wired/wifi/internet/vpn state
# Fields:
#   wired        - "yes"/"no" (ethernet link up)
#   wired_icon   - SVG path for wired state icon
#   display_icon - SVG path to show (VPN > wired priority)
#   wifi_on      - "yes"/"no" (adapter enabled)
#   wifi_icon    - Nerd Font glyph (signal bars or off)
#   ssid         - connected SSID or ""
#   online       - "full"/"local"/"none" (internet / LAN-only / disconnected)
#   vpn          - "on"/"off"

# SVG icons (baked with theme colors by theme-set)
ICON_DIR="$HOME/.config/eww/icons/status"
ICON_ONLINE="$ICON_DIR/network-wired-activated.svg"
ICON_LOCAL="$ICON_DIR/network-wired-no-internet.svg"
ICON_OFFLINE="$ICON_DIR/network-wired-disconnected.svg"
ICON_VPN="$ICON_DIR/network-vpn.svg"

# Check if NetworkManager is running (used to pick detection strategy)
nm_running() { nmcli -t general status &>/dev/null; }

# Hardware availability (detected once at startup -- doesn't change at runtime)
if nm_running; then
  _devtypes=$(nmcli -t -f TYPE device 2>/dev/null)
  if echo "$_devtypes" | grep -qi wifi; then HAS_WIFI=yes; else HAS_WIFI=no; fi
  if echo "$_devtypes" | grep -qi ethernet; then HAS_WIRED=yes; else HAS_WIRED=no; fi
else
  HAS_WIFI=no
  for d in /sys/class/net/*/wireless; do [[ -d "$d" ]] && { HAS_WIFI=yes; break; }; done
  HAS_WIRED=no
  for d in /sys/class/net/*/device; do
    dev=$(basename "$(dirname "$d")")
    [[ "$dev" == "lo" || -d "/sys/class/net/$dev/wireless" ]] && continue
    HAS_WIRED=yes; break
  done
fi

emit() {
  local wired="no" wired_icon="$ICON_OFFLINE"
  local wifi_on="no" wifi_icon=$'\U000f092e'
  local ssid="" online="none" vpn="off"

  if nm_running; then
    # ── NetworkManager path ──────────────────────────────────────────
    # Wired: check ALL ethernet devices, connected if any is
    while IFS=: read -r type state _; do
      if [[ "${type,,}" == "ethernet" && "$state" == "connected" ]]; then
        wired="yes"
        break
      fi
    done < <(nmcli -t -f TYPE,STATE device 2>/dev/null)

    # WiFi
    local wifi_hw
    wifi_hw=$(nmcli radio wifi 2>/dev/null || echo "disabled")
    if [[ "$wifi_hw" == "enabled" ]]; then
      wifi_on="yes"
      ssid=$(nmcli -t -f active,ssid dev wifi 2>/dev/null | grep '^yes' | cut -d: -f2)
      if [[ -n "$ssid" ]]; then
        local signal
        signal=$(nmcli -t -f active,signal dev wifi 2>/dev/null | grep '^yes' | cut -d: -f2)
        signal=${signal:-0}
        if   (( signal > 80 )); then wifi_icon=$'\U000f0928'
        elif (( signal > 60 )); then wifi_icon=$'\U000f0925'
        elif (( signal > 40 )); then wifi_icon=$'\U000f0922'
        elif (( signal > 20 )); then wifi_icon=$'\U000f091f'
        else                         wifi_icon=$'\U000f092f'
        fi
      else
        wifi_icon=$'\U000f092d'
      fi
    fi

    # Connectivity: "full" = internet, "limited"/"portal" = local only
    local nm_conn
    nm_conn=$(nmcli networking connectivity check 2>/dev/null || echo "unknown")
    if [[ "$nm_conn" == "full" ]]; then
      online="full"
    elif [[ "$nm_conn" == "limited" || "$nm_conn" == "portal" ]]; then
      online="local"
    fi

    # VPN: detect any active VPN/WireGuard/tunnel via NM connections
    local vpn_name
    vpn_name=$(nmcli -t -f name,type connection show --active 2>/dev/null \
      | grep -iE '(wireguard|vpn|tun)' | head -1 | cut -d: -f1)
    [[ -n "$vpn_name" ]] && vpn="on"
  else
    # ── Fallback: ip link / ip addr (NM not running) ────────────────
    local iface
    for iface in /sys/class/net/*/; do
      iface=$(basename "$iface")
      [[ "$iface" == "lo" ]] && continue
      local operstate
      operstate=$(< /sys/class/net/"$iface"/operstate)
      if [[ "$operstate" == "up" ]] && ip addr show "$iface" 2>/dev/null | grep -q 'inet '; then
        wired="yes"
        break
      fi
    done

    # Connectivity: quick ping for internet, then check local
    if ping -c1 -W2 1.1.1.1 &>/dev/null; then
      online="full"
    elif [[ "$wired" == "yes" ]]; then
      # Link is up but no internet — local-only
      online="local"
    fi

    # VPN: check for active WireGuard or tun/tap interfaces
    local _vpn_iface
    _vpn_iface=$(ip -o link show 2>/dev/null | grep -oP '\d+: \K(tun|wg)\S*' | head -1)
    if [[ -n "$_vpn_iface" ]]; then
      vpn="on"
    fi
  fi

  # Display icon priority: VPN > connectivity-aware wired icon
  # 3 states: connected (internet OK), local-only (LAN but no internet), disconnected
  local display_icon="$ICON_OFFLINE"
  if [[ "$wired" == "yes" || -n "$ssid" ]]; then
    if [[ "$online" == "full" ]]; then
      display_icon="$ICON_ONLINE"
    elif [[ "$online" == "local" ]]; then
      display_icon="$ICON_LOCAL"
    else
      display_icon="$ICON_OFFLINE"
    fi
  fi
  [[ "$vpn" == "on" ]] && display_icon="$ICON_VPN"

  printf '{"wired":"%s","wired_icon":"%s","display_icon":"%s","wifi_on":"%s","wifi_icon":"%s","ssid":"%s","online":"%s","vpn":"%s","wifi_available":"%s","wired_available":"%s"}\n' \
    "$wired" "$wired_icon" "$display_icon" "$wifi_on" "$wifi_icon" "$ssid" "$online" "$vpn" "$HAS_WIFI" "$HAS_WIRED"
}

emit

if nm_running; then
  nmcli monitor 2>/dev/null | while read -r _; do
    emit
  done
else
  # Poll when NM is absent; also re-check if NM starts later
  while sleep 5; do
    emit
    nm_running && exec "$0"   # NM came up, restart with monitor
  done
fi
