#!/usr/bin/env python3
import click

from collections import namedtuple
from pathlib import Path
from typing import Any, Generator, Iterable, Optional, Union

import contextlib
import os
import secrets
import string
import subprocess
import sys
import tempfile
import time
import urllib.request

NAME = 'vault'
DEFAULT_STORAGE = Path.home()/f'.{NAME}'
DEFAULT_TEMP = Path('/dev/shm')
DEFAULT_PASSWORD_CHARSET = string.ascii_letters + string.digits
DEFAULT_PASSWORD_LENGTH = 32
DEFAULT_PASSPHRASE_LENGTH = 6
DEFAULT_CLIPBOARD_TIMEOUT = 15
DEFAULT_KEYBOARD_DELAY = 2
SESSION_TYPE = 'wayland' if os.environ.get('WAYLAND_DISPLAY') else 'x11' if os.environ.get('DISPLAY') else None
WORDLIST_URL = 'https://www.eff.org/files/2016/07/18/eff_large_wordlist.txt'
GPG_OPTS = ['--quiet', '--compress-algo=none', '--no-encrypt-to']
if not SESSION_TYPE:
    GPG_OPTS.append('--pinentry-mode=loopback')
FZF_OPTS = ['--layout', 'reverse']
CONTENT_ENCODING = 'utf-8'
CLICK_SETTINGS = dict(help_option_names=['-h', '--help'])

Context = namedtuple('Context', ('storage', 'temp'))


def _complete_path(incomplete: str, **kwargs: Any) -> list[str]:
    # ctx.obj is not initialized
    ctx = _load_context()
    subdir = ctx.storage/incomplete
    subdir = subdir if subdir.exists() else subdir.parent
    candidates = (_unresolve(ctx, path) for path in _iter(subdir, **kwargs))
    return [name for name in candidates if name.startswith(incomplete)]


def _complete_entry(ctx: click.Context, _param: click.Parameter, incomplete: str) -> list[str]:
    return _complete_path(incomplete, recursive=True)


def _complete_subdir(ctx: click.Context, _param: click.Parameter, incomplete: str) -> list[str]:
    return _complete_path(incomplete, recursive=True, include_dirs=True, include_files=False)


def _load_context() -> Context:
    storage = Path(os.environ.get('VAULT_STORAGE', DEFAULT_STORAGE))
    temp = Path(os.environ.get('VAULT_TEMP', DEFAULT_TEMP))
    return Context(storage, temp)


@click.group(context_settings=CLICK_SETTINGS)
@click.pass_context
def cli(ctx: click.Context):
    ctx.obj = _load_context()


@cli.command()
@click.option('-f', '--force', is_flag=True)
@click.argument('keyid')
@click.argument('subdir', shell_complete=_complete_subdir, required=False)
@click.pass_context
def init(ctx: click.Context, keyid: str, subdir: Optional[str], force: bool):
    base = _resolve_subdir(ctx.obj, subdir) if subdir else ctx.obj.storage
    keyfile = base/'.gpg-id'
    if keyfile.is_file():
        if not force:
            raise click.UsageError('already initialized')
        recipients = _read_gpgid(keyfile)
    else:
        recipients = set()
    recipients.add(keyid)
    base.mkdir(exist_ok=True, parents=True)
    _write_gpgid(keyfile, recipients)
    for path in _iter(base):
        content = _load(path)
        _store(ctx.obj, path, content)


@cli.command()
@click.argument('name', shell_complete=_complete_entry)
@click.pass_context
def create(ctx: click.Context, name: str):
    entry = _resolve_entry(ctx.obj, name)
    if entry.exists():
        raise click.UsageError('secret already exists')
    if sys.stdin.isatty():
        with _tempfile(ctx.obj) as path:
            _edit(path)
            content = path.read_bytes()
        _store(ctx.obj, entry, content)
    else:
        _store(ctx.obj, entry, sys.stdin.buffer.read())


@cli.command()
@click.argument('name', shell_complete=_complete_entry)
@click.argument('keys', nargs=-1, required=False)
@click.pass_context
def read(ctx: click.Context, name: str, keys: list[str]):
    entry = _resolve_entry(ctx.obj, name)
    if not entry.is_file():
        raise click.UsageError('secret does not exist')
    lines = list(_read(entry, keys))
    for line in lines:
        _println(line, force=len(keys) > 1)


@cli.command()
@click.argument('name', shell_complete=_complete_entry)
@click.argument('key', required=False)
@click.pass_context
def update(ctx: click.Context, name: str, key: Optional[str]):
    entry = _resolve_entry(ctx.obj, name)
    if not entry.is_file():
        raise click.UsageError('secret does not exist')
    content = _load(entry)
    if sys.stdin.isatty():
        if key:
            raise click.UsageError('single key can not be updated interactively')
        with _tempfile(ctx.obj) as temp:
            temp.write_bytes(content)
            _edit(temp)
            content = temp.read_bytes()
    elif key:
        attrs = _parse(content)
        attrs[key] = sys.stdin.read()
        content = _format(attrs)
    else:
        content = sys.stdin.buffer.read()
    _store(ctx.obj, entry, content)


@cli.command()
@click.argument('name', shell_complete=_complete_entry)
@click.pass_context
def delete(ctx: click.Context, name: str):
    entry = _resolve_entry(ctx.obj, name)
    if not entry.is_file():
        raise click.UsageError('secret does not exist')
    _delete(ctx.obj.storage, entry)


@cli.command()
@click.option('-f', '--force', is_flag=True)
@click.argument('source', shell_complete=_complete_entry)
@click.argument('destination', shell_complete=_complete_entry)
@click.pass_context
def copy(ctx: click.Context, source: str, destination: str, force: bool):
    _copy(ctx.obj, _resolve_entry(ctx.obj, source), _resolve_entry(ctx.obj, destination), force)


@cli.command()
@click.option('-f', '--force', is_flag=True)
@click.argument('source', shell_complete=_complete_entry)
@click.argument('destination', shell_complete=_complete_entry)
@click.pass_context
def move(ctx: click.Context, source: str, destination: str, force: bool):
    _move(ctx.obj, _resolve_entry(ctx.obj, source), _resolve_entry(ctx.obj, destination), force)


@cli.command()
@click.option('-t', '--timeout', envvar='VAULT_CLIPBOARD_TIMEOUT', default=DEFAULT_CLIPBOARD_TIMEOUT, type=click.IntRange(min=0))
@click.argument('name', shell_complete=_complete_entry)
@click.argument('keys', nargs=-1, required=False)
@click.pass_context
def clip(ctx: click.Context, name: str, keys: list[str], timeout: int):
    entry = _resolve_entry(ctx.obj, name)
    if SESSION_TYPE == 'wayland':
        content = '\n'.join(_read(entry, keys))
        subprocess.run(['wl-copy'], input=content, text=True, check=True)
        pid = os.fork()
        if pid != 0:
            return
        time.sleep(timeout)
        subprocess.run(['wl-copy', '--clear'], input=content, check=True)
    elif SESSION_TYPE == 'x11':
        content = '\n'.join(_read(entry, keys))
        subprocess.run(['xclip', '-selection', 'clipboard'], input=content, text=True, check=True)
        pid = os.fork()
        if pid != 0:
            return
        time.sleep(timeout)
        subprocess.run(['xclip', '-selection', 'clipboard'], input=b'', check=True)
    else:
        raise click.UsageError('unsupported session type')


@cli.command()
@click.option('-d', '--delay', envvar='VAULT_KEYBOARD_DELAY', default=DEFAULT_KEYBOARD_DELAY, type=click.IntRange(min=0))
@click.argument('name', shell_complete=_complete_entry)
@click.argument('keys', nargs=-1, required=False)
@click.pass_context
def type(ctx: click.Context, name: str, keys: list[str], delay: int):
    entry = _resolve_entry(ctx.obj, name)
    if SESSION_TYPE == 'x11':
        content = '\t'.join(_read(entry, keys))
        # running setxkbmap before xdotool works around a bug in xdotool
        # see https://github.com/jordansissel/xdotool/issues/49
        subprocess.run(['setxkbmap'])
        pid = os.fork()
        if pid != 0:
            return
        time.sleep(delay)
        subprocess.run(['xdotool', 'type', '--clearmodifiers', '--file', '-'], input=content, text=True, check=True)
    else:
        raise click.UsageError('unsupported session type')


@cli.command()
@click.option('-c', '--charset', envvar='VAULT_PASSWORD_CHARSET', default=DEFAULT_PASSWORD_CHARSET)
@click.option('-l', '--length', envvar='VAULT_PASSWORD_LENGTH', default=DEFAULT_PASSWORD_LENGTH)
def generate_password(charset, length):
    _println(_generate_password(charset, length))


@cli.command()
@click.option('-l', '--length', envvar='VAULT_PASSPHRASE_LENGTH', default=DEFAULT_PASSPHRASE_LENGTH)
def generate_passphrase(length):
    _println(_generate_passphrase(length))


@cli.command('list')
@click.argument('subdir', shell_complete=_complete_subdir, required=False)
@click.pass_context
def list_command(ctx: click.Context, subdir: Optional[str]):
    base = _resolve_subdir(ctx.obj, subdir) if subdir else ctx.obj.storage
    for path in sorted(_iter(base, recursive=False, include_dirs=True)):
        _println(_unresolve(ctx.obj, path), force=True)


@cli.command()
@click.argument('string', required=False)
@click.pass_context
def find(ctx: click.Context, string: Optional[str]):
    for path in _iter(ctx.obj.storage):
        name = _unresolve(ctx.obj, path)
        if not string or string in name:
            _println(name, force=True)


@cli.command()
@click.argument('subdir', shell_complete=_complete_subdir, required=False)
@click.pass_context
def select(ctx: click.Context, subdir: Optional[str]):
    base = _resolve_subdir(ctx.obj, subdir) if subdir else ctx.obj.storage
    names = '\n'.join(_unresolve(ctx.obj, path) for path in _iter(base))
    name = subprocess.check_output(['fzf', '--no-multi', *FZF_OPTS], text=True, input=names).rstrip()
    attrs = _parse(_load(_resolve_entry(ctx.obj, name)))
    keys = subprocess.check_output(['fzf', '--multi', *FZF_OPTS], text=True, input='\n'.join(attrs.keys())).splitlines()
    for key in keys:
        _println(attrs[key], force=len(keys) > 1)


@cli.command()
@click.argument('name', shell_complete=_complete_entry)
@click.pass_context
def load(ctx: click.Context, name: str):
    entry = _resolve_entry(ctx.obj, name)
    if not entry.is_file():
        raise click.UsageError('secret does not exist')
    sys.stdout.buffer.write(_load(entry))


@cli.command()
@click.argument('name', shell_complete=_complete_entry)
@click.pass_context
def store(ctx: click.Context, name: str):
    entry = _resolve_entry(ctx.obj, name)
    entry.parent.mkdir(parents=True, exist_ok=True)
    _store(ctx.obj, entry, sys.stdin.buffer.read())


def _delete(root: Path, entry: Path) -> None:
    entry.unlink()
    _rmdir_recursive(root, entry.parent)


def _copy(ctx: Context, source: Path, destination: Path, force: bool) -> None:
    if not source.is_file():
        raise click.UsageError('source does not exist')
    if destination.is_dir():
        destination = destination/source.name
    if destination.exists() and not force:
        raise click.UsageError('destination already exists')
    content = _load(source)
    _store(ctx, destination, content)


def _move(ctx: Context, source: Path, destination: Path, force: bool) -> None:
    _copy(ctx, source, destination, force)
    _delete(ctx.storage, source)


def _generate_password(charset: str, length: int) -> str:
    return ''.join(secrets.choice(charset) for _ in range(length))


def _generate_passphrase(length: int) -> str:
    words = _load_wordlist()
    return ' '.join(words[_random_index()] for _ in range(length))


def _read(entry: Path, keys: list[str]) -> Generator[str, None, None]:
    content = _load(entry)
    if not keys:
        yield _decode(content)
    attrs = _parse(content)
    for key in keys:
        yield attrs[key]


def _load(entry: Path) -> bytes:
    content = entry.read_bytes()
    output = _gpg('--decrypt', input=content)
    return output


def _store(ctx: Context, entry: Path, content: bytes) -> None:
    recipient_opts = list()
    for address in _read_gpgid(_find_gpgid(ctx.storage, entry)):
        recipient_opts.extend(('--recipient', address))
    output = _gpg(*recipient_opts, '--encrypt', input=content)
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_bytes(output)


def _gpg(*args: str, input: bytes = b'') -> bytes:
    process = subprocess.run(['gpg', *GPG_OPTS, *args], check=True, input=input, capture_output=True)
    return process.stdout


def _resolve_subdir(ctx: Context, name: str) -> Path:
    subdir = ctx.storage/name
    assert ctx.storage in subdir.parents
    return subdir


def _resolve_entry(ctx: Context, name: str) -> Path:
    entry = ctx.storage/f'{name}.gpg'
    assert ctx.storage in entry.parents
    return entry


def _unresolve(ctx: Context, entry: Path) -> str:
    return entry.relative_to(ctx.storage).as_posix().removesuffix('.gpg')


def _read_gpgid(path: Path) -> set[str]:
    return {line.rstrip() for line in _decode(path.read_bytes()).splitlines()}


def _write_gpgid(path: Path, recipients: Iterable[str]) -> None:
    path.write_text('\n'.join(sorted(recipients)))


def _find_gpgid(root: Path, entry: Path) -> Path:
    subdir = entry.parent
    while root in subdir.parents or root == subdir:
        path = subdir/'.gpg-id'
        if path.is_file():
            return path
        subdir = subdir.parent
    raise click.UsageError('not initialized')


def _println(text: Optional[Union[str, bytes, Path]], force: bool = False):
    if text is None:
        return
    if isinstance(text, bytes):
        pass
    elif isinstance(text, str):
        text = text.encode('utf8')
    elif isinstance(text, Path):
        text = text.as_posix().encode('utf8')
    else:
        raise TypeError("argument 'text' has unexpected type")
    sys.stdout.buffer.write(text.rstrip())
    if sys.stdout.isatty() or force:
        sys.stdout.buffer.write(b'\n')


def _rmdir_recursive(root, path: Path) -> None:
    while root in path.parents:
        try:
            path.rmdir()
            path = path.parent
        except FileNotFoundError:
            return
        except OSError as e:
            # return on "directory not empty"
            if e.errno == 39:
                return
            raise


def _load_wordlist() -> dict[str, str]:
    cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache'))/NAME/'wordlist.txt'
    if cache.is_file():
        text = cache.read_text()
    else:
        with urllib.request.urlopen(WORDLIST_URL) as response:
            text = response.read().decode('utf-8')
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(text)
    return dict(line.strip().split('\t', maxsplit=1) for line in text.splitlines())


def _random_index() -> str:
    return ''.join(secrets.choice('123456') for _ in range(5))


def _parse(content: bytes) -> dict[str, str]:
    lines = _decode(content).splitlines()
    password = lines.pop(0) if lines else ''
    attrs = dict(password=password)
    for number, line in enumerate(lines):
        if not line:
            continue
        blocks = line.split(': ', maxsplit=1)
        if len(blocks) != 2:
            raise click.UsageError(f'parser error in line {number}: invalid key-value format')
        key, value = blocks
        if key == 'password':
            raise click.UsageError(f'parser error in line {number}: disallowed key {key!r}')
        if key in attrs:
            raise click.UsageError(f'parser error in line {number}: repeated key {key!r}')
        attrs[key] = value
    return attrs


def _format(attrs: dict[str, str]) -> bytes:
    lines = list()
    lines.append(attrs.pop('password', ''))
    for key, value in attrs.items():
        if ':' in key or ' ' in key:
            raise click.UsageError(f'parser error: key {key!r} contains illegal character')
        lines.append(f'{key}: {value}')
    return _encode('\n'.join(lines))


def _encode(data: str) -> bytes:
    return data.encode(CONTENT_ENCODING, errors='strict')


def _decode(data: bytes) -> str:
    return data.decode(CONTENT_ENCODING, errors='strict')


def _iter(base: Path, recursive=True, include_dirs=False, include_files=True):
    for path in base.iterdir():
        if path.name.startswith('.'):
            continue
        elif path.is_file():
            if path.name.endswith('.gpg') and include_files:
                yield path
        elif path.is_dir():
            if include_dirs:
                yield path
            if recursive:
                yield from _iter(path, recursive=True, include_dirs=include_dirs, include_files=include_files)


@contextlib.contextmanager
def _tempfile(ctx: Context) -> Generator[Path, None, None]:
    _, path = tempfile.mkstemp(dir=ctx.temp, prefix=f'{NAME}-', suffix='.txt')
    path = Path(path)
    try:
        yield path
    finally:
        if path.exists():
            path.unlink()


def _edit(path: Path) -> None:
    editor = os.environ.get('EDITOR', 'vim')
    if editor.endswith('nvim'):
        command = [editor, '-c', 'set nobackup noswapfile noundofile shada="NONE"', '--', path]
    elif editor.endswith('vim'):
        command = [editor, '-c', 'set nobackup noswapfile noundofile viminfo=', '--', path]
    else:
        command = [editor, path]
    before = os.stat(path).st_mtime_ns
    process = subprocess.run(command, check=False)
    after = os.stat(path).st_mtime_ns
    if process.returncode != 0 or after <= before:
        raise click.UsageError('edit aborted')


if __name__ == '__main__':
    cli()
