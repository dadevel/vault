# Vault

A simple secret store inspired by [pass](https://www.passwordstore.org/), powered by gpg and written in python.

In comparison with pass:

- vault doesn't feature git integration, it's intended to be used with external synchronization solutions like [Nextcloud](https://nextcloud.com/) or [Syncthing](https://syncthing.net/)
- vault can generate [diceware](https://wikipedia.org/wiki/Diceware) passphrases based on a [wordlist](https://www.eff.org/dice)

## Setup

Requirements:

- Python 3.9 or later
- GnuPG 2
- your favourite text editor

Some subcommands have additional dependencies:

Command  | Dependency
---------|-------------
clip     | `xclip` on X11, `wl-copy` on Wayland
type     | `setxkbmap` and `xdotool` on X11, currently not supported on Wayland
select   | `fzf`

Installation:

~~~ bash
pip3 install --user --upgrade git+https://github.com/dadevel/vault.git
~~~

Shell completion for bash, zsh and fish:

~~~ bash
eval "$(_VAULT_COMPLETE=$(basename $SHELL)_source vault)"
~~~

## Usage

Initialize your vault with the GPG key for `jane.doe@example.com`.

~~~ bash
vault init jane.doe@example.com
~~~

Add your first secret.

~~~ bash
vault generate-password | vault create example.com/jane
vault update example.com/jane
~~~

Get help.

~~~ bash
vault --help
~~~

## Integrations

- [Password Store](https://github.com/android-password-store/Android-Password-Store) app on Android
- [Browserpass](https://github.com/browserpass/browserpass-extension) web extension for browser integration
