#!/usr/bin/env bash
# Idempotent VPS provisioning for Portfolio Thesis Engine (Ubuntu 24.04).
#
# Safe to re-run on a VPS that has already been provisioned manually —
# every step detects prior state and skips when already satisfied. Does
# NOT touch SSH hardening or ufw (managed out-of-band).
#
# Usage:
#   ./scripts/provision_vps.sh
#
# Requires: sudo without password prompt OR an interactive TTY.

set -euo pipefail

ACTIONS=()
SKIPPED=()

note_action() { ACTIONS+=("$1"); printf '  \033[32m+\033[0m %s\n' "$1"; }
note_skip()   { SKIPPED+=("$1"); printf '  \033[2m-\033[0m %s (already present)\n' "$1"; }

apt_ensure() {
    # apt_ensure <binary-to-check> <apt-package>
    local bin="$1"
    local pkg="${2:-$1}"
    if command -v "$bin" >/dev/null 2>&1; then
        note_skip "$pkg"
    else
        sudo apt install -y "$pkg" >/dev/null
        note_action "$pkg"
    fi
}

apt_ensure_dpkg() {
    # apt_ensure_dpkg <apt-package>   — for packages without a unique binary name
    local pkg="$1"
    if dpkg -s "$pkg" >/dev/null 2>&1; then
        note_skip "$pkg"
    else
        sudo apt install -y "$pkg" >/dev/null
        note_action "$pkg"
    fi
}

echo "=== Portfolio Thesis Engine — VPS provisioning (idempotent) ==="
echo

# ---------------------------------------------------------------------
echo "[1] apt update"
sudo apt-get update -qq
echo "    done."
echo

# ---------------------------------------------------------------------
echo "[2] Essential packages"
for pair in \
    "git:git" \
    "curl:curl" \
    "wget:wget" \
    "tmux:tmux" \
    "htop:htop" \
    "jq:jq" \
    "rclone:rclone" \
    "sqlite3:sqlite3" \
    "fail2ban-client:fail2ban"
do
    bin="${pair%%:*}"
    pkg="${pair##*:}"
    apt_ensure "$bin" "$pkg"
done
# build-essential has no unique binary — use dpkg
apt_ensure_dpkg build-essential
echo

# ---------------------------------------------------------------------
echo "[3] Python 3.12"
if command -v python3.12 >/dev/null 2>&1; then
    note_skip "python3.12"
else
    sudo apt install -y python3.12 python3.12-venv python3.12-dev python3-pip >/dev/null
    note_action "python3.12 + venv/dev/pip"
fi
echo

# ---------------------------------------------------------------------
echo "[4] uv package manager"
if command -v uv >/dev/null 2>&1 || [ -x "$HOME/.local/bin/uv" ] || [ -x "$HOME/.cargo/bin/uv" ]; then
    note_skip "uv"
else
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
    # Make it available in the rest of this script
    if [ -f "$HOME/.local/bin/uv" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    elif [ -f "$HOME/.cargo/bin/uv" ]; then
        export PATH="$HOME/.cargo/bin:$PATH"
    fi
    note_action "uv installed"
fi
echo

# ---------------------------------------------------------------------
echo "[5] Tailscale"
if command -v tailscale >/dev/null 2>&1; then
    note_skip "tailscale"
else
    curl -fsSL https://tailscale.com/install.sh | sh >/dev/null
    note_action "tailscale installed (run 'sudo tailscale up' to authenticate)"
fi
echo

# ---------------------------------------------------------------------
echo "[6] fail2ban running"
if systemctl is-active --quiet fail2ban; then
    note_skip "fail2ban service"
else
    sudo systemctl enable --now fail2ban >/dev/null 2>&1
    note_action "fail2ban service started"
fi
echo

# ---------------------------------------------------------------------
echo "=== Summary ==="
echo "Applied: ${#ACTIONS[@]}"
echo "Skipped: ${#SKIPPED[@]} (already present)"
echo
echo "NOT managed by this script (handle out-of-band):"
echo "  • SSH hardening"
echo "  • ufw / nftables rules"
echo "  • systemd units for pte-streamlit / pte-backup (symlink those manually"
echo "    after reviewing systemd/*.service + .timer)"
