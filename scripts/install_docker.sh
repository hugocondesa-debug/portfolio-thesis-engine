#!/bin/bash
# Install Docker Engine + Compose plugin on Ubuntu 24 (Hetzner VPS).
# Idempotent — re-running on an installed system is a no-op.
set -euo pipefail

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "Docker already installed:"
  docker --version
  docker compose version
  exit 0
fi

echo "Installing Docker..."

# Add Docker's official GPG key.
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the Docker apt repository.
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y \
  docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

# Allow the current user to run docker without sudo (group-membership
# changes require re-login or `newgrp docker`).
sudo usermod -aG docker "$USER"

echo
echo "Docker installed."
echo "  docker --version           → $(docker --version)"
echo "  docker compose version     → $(docker compose version | head -1)"
echo
echo "Group changes take effect on next login. To apply now:"
echo "  newgrp docker"
echo
echo "Then verify with:"
echo "  docker run --rm hello-world"
