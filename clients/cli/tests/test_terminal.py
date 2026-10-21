"""Exercise real terminal key bindings and plain redirected-input fallback."""
import io
import unittest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output.vt100 import Vt100_Output
from membrain_cli.terminal import highlighted, select


class TerminalTests(unittest.TestCase):
    def choose(self, keys):
        output = io.StringIO()
        with create_pipe_input() as terminal_input:
            terminal_input.send_text(keys)
            result = highlighted('Menu', [('1', 'First'), ('2', 'Second'), ('x', 'Exit')],
                                 input=terminal_input,
                                 output=Vt100_Output(output, lambda: Size(rows=24, columns=100),
                                                     term='xterm-256color', enable_cpr=False))
        return result, output.getvalue()

    def test_arrows_and_enter(self):
        self.assertEqual(self.choose('\x1b[B\r')[0], '2')
        self.assertEqual(self.choose('\x1b[B\x1b[A\r')[0], '1')
        self.assertEqual(self.choose('\x1b[A\r')[0], 'x')

    def test_typed_commands_and_numbers(self):
        self.assertEqual(self.choose('/help\r')[0], '/help')
        self.assertEqual(self.choose('2\r')[0], '2')
        self.assertEqual(self.choose('x\r')[0], 'x')

    def test_arrow_clears_typed_input(self):
        self.assertEqual(self.choose('99\x1b[B\r')[0], '2')

    def test_highlight_and_hint_are_rendered(self):
        _, output = self.choose('\r')
        self.assertIn('❯', output)
        self.assertIn('Enter confirm', output)
        self.assertIn(';7', output)  # ANSI reverse-video selection style.

    def test_interrupt_and_eof(self):
        for keys, error in [('\x03', KeyboardInterrupt), ('\x04', EOFError)]:
            with self.assertRaises(error): self.choose(keys)

    def test_scripted_input_uses_plain_menu(self):
        output = []
        self.assertEqual(select('Menu', [('1', 'First')], read=lambda _: '1', write=output.append), '1')
        self.assertIn('1. First', output)

    def test_background_tick_runs_before_enter_without_losing_typed_input(self):
        output=io.StringIO();ticks=[]
        with create_pipe_input() as terminal_input:
            terminal_input.send_text('draft')
            def tick():
                ticks.append(True)
                terminal_input.send_text('\r')
            result=highlighted('Menu',[('1','First')],input=terminal_input,
                output=Vt100_Output(output,lambda:Size(rows=24,columns=100),term='xterm-256color',enable_cpr=False),tick=tick)
        self.assertEqual(result,'draft')
        self.assertTrue(ticks)
