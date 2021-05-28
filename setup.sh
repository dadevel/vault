#!/bin/sh
PS4='> '
set -eux

PREFIX="${PREFIX:-/usr/local}"

cd "$(dirname "$0")"
install -m 0755 -D ./vault.sh "$PREFIX/bin/vault"
mkdir -p "$PREFIX/share/bash-completion/completions/"
echo 'eval "$(vault complete bash)"' > "$PREFIX/share/bash-completion/completions/vault"
