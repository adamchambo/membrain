"""Shared arrow menus and text input, preserving drafts during background output."""
import asyncio
from contextlib import nullcontext
import os
import sys


def interactive(read=input, write=print):
    """Enable terminal widgets for real read/write IO; retain plain redirected input."""
    return (read is input and write is print and sys.stdin.isatty() and
            sys.stdout.isatty() and os.environ.get('TERM') != 'dumb')


def select(title, choices, read=input, write=print, prompt='Choose: ', *, tick=None):
    """Select key/label choices under title; read/write support scripts, tick drains background work."""
    if not interactive(read, write):
        write('\n' + title)
        for key, label in choices:
            write(f'{key}. {label}')
        return read(prompt)
    return highlighted(title, choices, prompt, tick=tick)


def _prompt(session, message, tick=None, *, managed_output=True):
    """Prompt with session/message; optionally call tick while safely redrawing managed output."""
    from prompt_toolkit.patch_stdout import patch_stdout

    async def refresh():
        while True:
            await asyncio.sleep(.25)
            tick()

    def ready():
        if tick:
            session.app.create_background_task(refresh())

    with patch_stdout(raw=True) if managed_output else nullcontext():
        return session.prompt(message, pre_run=ready)


def read_text(prompt, read=input, write=print, *, tick=None):
    """Read text at prompt with injected read/write fallback and optional background tick."""
    if not interactive(read, write):
        return read(prompt)
    from prompt_toolkit import PromptSession
    return _prompt(PromptSession(), prompt, tick)


def highlighted(title, choices, prompt='Choose: ', *, input=None, output=None, tick=None):
    """Render title and key/label choices; input/output inject toolkit terminals, tick handles events."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style

    selected = 0
    keys = KeyBindings()

    @keys.add('up')
    @keys.add('down')
    def move(event):
        nonlocal selected
        selected = (selected + (1 if event.key_sequence[-1].key == 'down' else -1)) % len(choices)
        event.current_buffer.reset()
        event.app.invalidate()

    @keys.add('enter')
    def accept(event):
        event.app.exit(result=event.current_buffer.text.strip() or choices[selected][0])

    def message():
        rows = [('', '\n' + title + '\n'), ('class:hint', '↑/↓ select · Enter confirm · or type a number/command\n')]
        for index, (key, label) in enumerate(choices):
            rows.append(('class:selected' if index == selected else '',
                         f'{"❯" if index == selected else " "} {key}. {label}\n'))
        rows.append(('', prompt))
        return rows

    session = PromptSession(input=input, output=output, key_bindings=keys,
                            style=Style.from_dict({'selected': 'reverse bold', 'hint': 'italic'}))
    return _prompt(session, message, tick, managed_output=output is None)
