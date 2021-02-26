#!/usr/bin/env bash
set -euo pipefail

if [[ -v VAULT_DEBUG ]]; then
    set -x
fi

declare -ra GPG_OPTS=(--quiet --compress-algo=none --no-encrypt-to)
declare -r WORDLIST_URL='https://www.eff.org/files/2016/07/18/eff_large_wordlist.txt'

declare -r VAULT_STORAGE="${VAULT_STORAGE:-$HOME/.vault}"
declare -r VAULT_TEMP_DIR="${VAULT_TEMP_DIR:-/dev/shm}"
declare -r VAULT_CLIPBOARD_TIMEOUT="${VAULT_CLIPBOARD_TIMEOUT:-30}"
declare -r VAULT_KEYBOARD_DELAY="${VAULT_KEYBOARD_DELAY:-3}"
declare -r VAULT_PASSWORD_CHARSET="${VAULT_PASSWORD_CHARSET:-[:alnum:]}"
declare -r VAULT_PASSWORD_LENGTH="${VAULT_PASSWORD_LENGTH:-16}"
declare -r VAULT_PASSPHRASE_LENGTH="${VAULT_PASSPHRASE_LENGTH:-6}"

main() {
    case "$#:$@" in
        3:init\ *)
            shift
            if [[ -f "$VAULT_STORAGE/$1/.gpg-id" ]]; then
                echo vault already initalized >&2
                exit 1
            fi
            mkdir -p "$VAULT_STORAGE/$1"
            echo "$2" > "$VAULT_STORAGE/$1/.gpg-id"
            ;;
        2:init\ *)
            shift
            "$0" init . "$1"
            ;;
        1:tree|2:tree\ *)
            shift
            cd "$VAULT_STORAGE"
            tree -P '*.gpg' --prune --dirsfirst --sort=version "${1:-.}" | sed 's|.gpg$||'
            ;;
        1:list|2:list\ *)
            shift
            cd "$VAULT_STORAGE"
            find "${1:-.}" -mindepth 1 -maxdepth 1 ! -type l ! -name '.*' | sed 's|^./||;s|.gpg$||' | sort -V
            ;;
        1:find|2:find\ *)
            shift
            cd "$VAULT_STORAGE"
            find . -mindepth 1 -type f -path "*${1:-}*.gpg" | sed 's|^./||;s|.gpg$||' | sort -V
            ;;
        *:show\ *\ password)
            shift
            "$0" read "$1" | head -n 1 | tr -d '\n'
            ;;
        *:show\ *\ *)
            shift
            "$0" read "$1" | tail -n +2 | while read -r line; do
                if [[ "${line}" =~ ^"$2":\ (.+)$ ]]; then
                    echo -n "${BASH_REMATCH[1]}"
                    exit
                fi
            done
            echo key not found >&2
            exit 1
            ;;
        *:clip\ *)
            shift
            if [[ -v WAYLAND_DISPLAY && -n "$WAYLAND_DISPLAY" ]]; then
                "$0" show "$@" | wl-copy
                sleep "$VAULT_CLIPBOARD_TIMEOUT"
                wl-copy --clear
            elif [[ -v DISPLAY && -n "$DISPLAY" ]]; then
                "$0" show "$@" | xclip -selection clipboard
                sleep "$VAULT_CLIPBOARD_TIMEOUT"
                xclip -selection clipboard < /dev/null
            else
                echo no graphical environment detected >&2
                exit 1
            fi
            ;;
        *:type\ *)
            shift
            if [[ -v WAYLAND_DISPLAY && -n "$WAYLAND_DISPLAY" ]]; then
                echo feature not supported on wayland yet >&2
                exit 1
            elif [[ -v DISPLAY && -n "$DISPLAY" ]]; then
                # running setxkbmap before xdotool works around a bug in xdotool
                # see https://github.com/jordansissel/xdotool/issues/49
                sleep "$VAULT_KEYBOARD_DELAY"
                setxkbmap
                "$0" show "$@" | xdotool type --clearmodifiers --file -
            else
                echo no graphical environment detected >&2
                exit 1
            fi
            ;;
        2:generate\ password)
            set +o pipefail
            LC_ALL=C tr -dc "$VAULT_PASSWORD_CHARSET" < /dev/random | head -zc "$VAULT_PASSWORD_LENGTH"
            ;;
        3:generate\ password\ *)
            shift 2
            if [[ -f "$VAULT_STORAGE/$1.gpg" ]]; then
                echo secret already exists >&2
                exit 1
            fi
            "$0" generate password | "$0" create "$1"
            ;;
        2:generate\ passphrase)
            declare -r cache="${XDG_CACHE_HOME:-$HOME/.cache}/vault"
            if [[ ! -f "${cache}/wordlist.txt" ]]; then
                mkdir -p "${cache}"
                if type curl &> /dev/null; then
                    curl -sSo "${cache}/wordlist.txt" "$WORDLIST_URL"
                elif type wget &> /dev/null; then
                    wget -q -O "${cache}/wordlist.txt" "$WORDLIST_URL"
                else
                    echo no download utility found, please install curl or wget >&2
                    exit 1
                fi
            fi
            for (( i = 0; i < VAULT_PASSPHRASE_LENGTH; i++ )); do
                grep "^$(LC_ALL=C tr -dc '1-6' < /dev/random | head -zc 5)[[:space:]]" "${cache}/wordlist.txt"
            done | cut -d $'\t' -f 2- | paste -sd ' '
            ;;
        3:generate\ passphrase\ *)
            shift 2
            if [[ -f "$VAULT_STORAGE/$1.gpg" ]]; then
                echo secret already exists >&2
                exit 1
            fi
            "$0" generate passphrase | "$0" create "$1"
            ;;
        2:create\ *)
            shift
            if [[ -f "$VAULT_STORAGE/$1.gpg" ]]; then
                echo secret already exists >&2
                exit 1
            fi
            if [[ -t 0 ]]; then
                declare -r temp="$(tempfile)"
                edit "${temp}"
                "$0" store "$1" < "${temp}"
            else
                "$0" store "$1"
            fi
            ;;
        2:read\ *)
            shift
            if [[ ! -f "$VAULT_STORAGE/$1.gpg" ]]; then
                echo secret does not exist >&2
                exit 1
            fi
            "$0" load "$1"
            ;;
        2:update\ *)
            shift
            if [[ ! -f "$VAULT_STORAGE/$1.gpg" ]]; then
                echo secret does not exist >&2
                exit 1
            fi
            if [[ -t 0 ]]; then
                declare -r temp="$(tempfile)"
                "$0" load "$1" > "${temp}"
                edit "${temp}"
                "$0" store "$1" < "${temp}"
            else
                "$0" store "$1"
            fi
            ;;
        2:delete\ *)
            shift
            if [[ ! -f "$VAULT_STORAGE/$1.gpg" ]]; then
                echo secret does not exist >&2
                exit 1
            fi
            rm "$VAULT_STORAGE/$1.gpg"
            rmdir -p --ignore-fail-on-non-empty "$VAULT_STORAGE/${1%/*}"
            ;;
        2:load\ *)
            shift
            declare -r src="$VAULT_STORAGE/$1.gpg"
            if [[ ! -f "${src}" ]]; then
                echo secret does not exist >&2
                exit 1
            fi
            "$0" decrypt < "${src}"
            ;;
        2:store\ *)
            shift
            declare -r dst="$VAULT_STORAGE/$1.gpg"
            declare dir="${dst%/*}"
            while [[ "${dir}" != "$VAULT_STORAGE" && ! -f "${dir}/.gpg-id" ]]; do
                dir="${dir%/*}"
            done
            if [[ ! -f "${dir}/.gpg-id" ]]; then
                echo vault not initalized >&2
                exit 1
            fi
            declare -a recipients
            mapfile -t recipients < "${dir}/.gpg-id"
            mkdir -p "${dst%/*}"
            "$0" encrypt "${recipients[@]}" > "${dst}"
            ;;
        *:encrypt\ *)
            shift
            declare -a recipients=()
            for keyid in "$@"; do
                recipients+=(--recipient "${keyid}")
            done
            gpg "${GPG_OPTS[@]}" "${recipients[@]}" --encrypt
            ;;
        1:decrypt)
            gpg "${GPG_OPTS[@]}" --decrypt
            ;;
        2:complete\ bash)
            echo "$BASH_COMPLETION"
            ;;
        2:complete\ implementation|*:complete\ implementation\ *)
            shift 3
            declare -ra commands=(init list tree find show clip type generate create read update delete load store encrypt decrypt)
            if (( $# < 2 )); then
                for command in "${commands[@]}"; do
                    echo "${command} "
                done
            elif (( $# == 2 )); then
                if [[ "$1" == generate ]]; then
                    for command in "${generate_subcommands[@]}"; do
                        echo "${command} "
                    done
                elif [[ "${commands[@]}" == *"$1"* ]]; then
                    "$0" complete entry "$2"
                fi
            elif (( $# == 3 )); then
                if [[ "$1" == generate && "${generate_subcommands[@]}" == *"$2"* ]]; then
                    "$0" complete entry "$3"
                fi
            fi
            ;;
        3:complete\ entry\ *)
            shift 2
            if [[ ! -d "$VAULT_STORAGE/$1" && ! -f "$VAULT_STORAGE/$1.gpg" ]]; then
                IFS=/ read -ra parts <<< "$1"
                if [[ -n "${parts[@]}" ]]; then
                    unset parts[-1]
                fi
                set -- "$(IFS=/ && echo "${parts[*]}")"
            fi
            "$0" list "$1" | while read -r path; do
                if [[ -d "$VAULT_STORAGE/${path}/" ]]; then
                    echo "${path}/"
                elif [[ -f "$VAULT_STORAGE/${path}.gpg" ]]; then
                    echo "${path} "
                else
                    echo "${path}"
                fi
            done
            ;;
        1:help)
            echo "$HELP_TEXT"
            ;;
        *)
            echo bad arguments >&2
            "$0" help
            exit 1
            ;;
    esac
}

tempfile() {
    declare -r temp="$(mktemp "$VAULT_TEMP_DIR/vault-XXXXXXXX.txt")"
    chmod 0600 "${temp}"
    trap "rm -f ${temp@Q}" EXIT
    echo "${temp}"
}

edit() {
    if ! "${EDITOR:-vi}" "$1" || [[ "$(stat --printf=%s "$1")" == 0 ]]; then
        echo aborted >&2
        return 1
    fi
}

declare -r BASH_COMPLETION="$(cat << 'EOF'
_vault_completion() {
    declare -r IFS=$'\n'
    COMPREPLY=($(compgen -W "$(vault complete implementation "${COMP_WORDS[@]}")" -- "${COMP_WORDS[COMP_CWORD]}"))
}
complete -o nospace -F _vault_completion vault
EOF
)"
declare -r HELP_TEXT="$(cat << 'EOF'
usage: vault ACTION OPTIONS

actions:
  init KEYID [SUBDIR]       initialize vault
  list [SUBDIR]             list secrets
  tree [SUBDIR]             list secrets in tree view
  find [STRING]             search secrets
  show PATH KEY             print secret attribute
  clip PATH KEY             copy secret attribute to clipboard
  type PATH KEY             type secret attribute with keyboard
  generate password PATH    create secret with generated password
  generate passphrase PATH  create secret with generated passhphrase
  create PATH               add new secret
  read PATH                 print secret
  update PATH               change existing secret
  delete PATH               remove secret
  load PATH                 decrypt path to stdout
  store PATH                encrypt stdin to path
  encrypt KEYID...          encrypt stdin to stdout
  decrypt                   decrypt stdin to stdout
  complete bash             print bash completion snippet

environment:
  VAULT_STORAGE             directory to store files in, default: ~/.vault
  VAULT_TEMP_DIR            temporally place decrypted files there, default: /dev/shm
  VAULT_CLIPBOARD_TIMEOUT   seconds before clearing the clipboard, default: 30
  VAULT_KEYBOARD_DELAY      seconds to wait before to start typing, default: 3
  VAULT_PASSWORD_CHARSET    alphabet of generated passwords, default: [:alnum:]
  VAULT_PASSWORD_LENGTH     length of generated passwords, default: 16
  VAULT_PASSPHRASE_LENGTH   number of words in generated passphrases, default: 6
  VAULT_DEBUG               enable verbose output
  EDITOR                    program to edit secrets with, default: vi
EOF
)"

main "$@"

