# Vault

A simple secret store inspired by [pass](https://www.passwordstore.org/), powered by gpg and written in bash.

In comparison with pass:

- vault doesn't feature git integration, it's intended to be used with external synchronization solutions like [Nextcloud](https://nextcloud.com/) or [Syncthing](https://syncthing.net/)
- vault can generate [diceware](https://wikipedia.org/wiki/Diceware) passphrases based on a [wordlist](https://www.eff.org/dice)

## Setup

Requirements:

- bash
- gnupg
- basic utilities like coreutils, `find` and `sed`
- your favourite text editor

Some subcommands have additional dependencies:

Command               | Dependency
----------------------|-------------
`generate passphrase` | `curl` or `wget`
`tree`                | `tree`
`clip`                | `xclip` on X11 or `wl-copy` on Wayland
`type`                | `setxkbmap` and `xdotool` on X11, currently not supported on Wayland
`select`              | `fzf`

Installation:

~~~ bash
git clone --depth 1 https://github.com/dadevel/vault.git
sudo ./vault/setup.sh
~~~

## Usage

Initialize your vault.

~~~ bash
vault init jane.doe@example.org
~~~

Add your first secret.

~~~ bash
vault generate password example.org/jane
vault update example.org/jane
~~~

Get help.

~~~ bash
vault help
~~~

## Integrations

- [Password Store](https://github.com/android-password-store/Android-Password-Store) app on Android
- [Browserpass](https://github.com/browserpass/browserpass-extension) web extension for browser integration
