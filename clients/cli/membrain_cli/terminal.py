"""Shared terminal menus with arrow selection and typed command support."""
import os
import sys


def interactive(read=input, write=print):
    """Enable highlighting for real terminal read/write, retaining plain IO for scripts."""
    return (read is input and write is print and sys.stdin.isatty() and
            sys.stdout.isatty() and os.environ.get('TERM') != 'dumb')


def select(title, choices, read=input, write=print, prompt='Choose: '):
    """Show title and (key, label) choices; use read/write for plain IO and prompt for input."""
    if not interactive(read, write):
        write('\n' + title)
        for key, label in choices:
            write(f'{key}. {label}')
        return read(prompt)
    return highlighted(title, choices, prompt)


def highlighted(title, choices, prompt='Choose: ', *, input=None, output=None):
    """Render title and key/label choices; optional toolkit input/output support terminal tests."""
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
    return session.prompt(message)
