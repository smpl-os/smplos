#!/usr/bin/env bash

set -e

echo "Updating existing smplOS directory structure..."

ROOT="."

# Ensure required top-level dirs exist
mkdir -p $ROOT/{compositors,editions,installer,iso,shared}

###############################################
# Shared Layer
###############################################
mkdir -p $ROOT/shared/{configs,settings-panel,themes,system,bin}

touch $ROOT/shared/bin/.keep
touch $ROOT/shared/configs/.keep
touch $ROOT/shared/settings-panel/.keep
touch $ROOT/shared/themes/.keep
touch $ROOT/shared/system/.keep

###############################################
# Compositor: Hyprland
###############################################
mkdir -p $ROOT/compositors/hyprland/{configs}

[ ! -f $ROOT/compositors/hyprland/packages.txt ] && touch $ROOT/compositors/hyprland/packages.txt
[ ! -f $ROOT/compositors/hyprland/postinstall.sh ] && touch $ROOT/compositors/hyprland/postinstall.sh && chmod +x $ROOT/compositors/hyprland/postinstall.sh

###############################################
# Editions
###############################################
for edition in productivity creators communication development ai lite; do
    mkdir -p $ROOT/editions/$edition
    [ ! -f $ROOT/editions/$edition/packages-extra.txt ] && touch $ROOT/editions/$edition/packages-extra.txt
    [ ! -f $ROOT/editions/$edition/packages-aur-extra.txt ] && touch $ROOT/editions/$edition/packages-aur-extra.txt
    [ ! -f $ROOT/editions/$edition/postinstall-extra.sh ] && touch $ROOT/editions/$edition/postinstall-extra.sh && chmod +x $ROOT/editions/$edition/postinstall-extra.sh
done

###############################################
# Offline ISO Support
###############################################
mkdir -p $ROOT/iso/offline-repo/{x86_64,any}
mkdir -p $ROOT/iso/pacman-cache

touch $ROOT/iso/offline-repo/.keep
touch $ROOT/iso/pacman-cache/.keep

###############################################
# Installer + ISO builder
###############################################
mkdir -p $ROOT/installer

[ ! -f $ROOT/build-iso.sh ] && touch $ROOT/build-iso.sh && chmod +x $ROOT/build-iso.sh

echo "smplOS structure updated successfully."
