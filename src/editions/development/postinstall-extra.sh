#!/usr/bin/env bash
# smplOS Development Edition -- extra post-install hooks

# Enable libvirt daemon for QEMU/virt-manager
systemctl enable libvirtd.service

# Add user to libvirt group so virt-manager works without sudo
if [[ -n "${NEW_USER:-}" ]]; then
    usermod -aG libvirt "$NEW_USER"
fi
