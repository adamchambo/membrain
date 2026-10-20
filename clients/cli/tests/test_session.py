"""Exercise navigation and feedback without a terminal, server, or AI model."""
import unittest

from oracle_cli.session import Session
from oracle_cli.stub_api import StubAPI


class SessionTests(unittest.TestCase):
    def run_session(self, *inputs):
        values = iter(inputs)
        output = []
        backend = StubAPI()
        def read(prompt):
            try:
                return next(values)
            except StopIteration:
                raise EOFError from None
        session = Session(backend, read=read, write=output.append)
        session.run()
        return session, backend, "\n".join(output)

    def test_invalid_input_and_root_back_do_not_exit(self):
        _, _, output = self.run_session("/back", "999", "", "0")
        self.assertIn("Choose one of the displayed numbers", output)
        self.assertIn("Please enter a value", output)
        self.assertIn("Exiting stub session", output)

    def test_capture_preserves_text_and_handles_slash_commands(self):
        _, backend, _ = self.run_session("1", "1", "  My explanation  ", "/show", "/undo", "/menu", "0")
        self.assertEqual([call[0] for call in backend.calls], ["capture.message", "capture.inspect", "capture.undo"])
        self.assertEqual(backend.calls[0][1], "  My explanation  ")

    def test_review_hides_feedback_until_answer_and_retains_scope(self):
        _, backend, output = self.run_session("4", "2", "Binary", "1", "2", "My answer", "1", "Second answer", "4", "0")
        answers = [call for call in backend.calls if call[0] == "review.answer"]
        self.assertEqual(len(answers), 2)
        self.assertEqual(answers[0][2]["topic"], "Binary")
        self.assertEqual(answers[1][2]["review_format"], "teach")
        self.assertLess(output.index("[Stub teach question]"), output.index("Answer received"))
        self.assertIn("2 review answer(s)", output)

    def test_surprise_gap_diagnostic_does_not_claim_a_deficit(self):
        _, backend, output = self.run_session("5", "3", "1", "I know this", "2", "1", "/quit")
        self.assertIn("no personal evidence was inspected", output)
        self.assertIn("No gap established", output)
        self.assertIn("learn.lesson", [call[0] for call in backend.calls])

    def test_back_restores_previous_context(self):
        session, _, _ = self.run_session("5", "1", "Computers", "2", "Binary", "/back")
        self.assertEqual(session.current.screen, "gap_scope")
        self.assertEqual(session.current.context["topic"], "Computers")

    def test_search_then_review_uses_selected_concept(self):
        _, backend, _ = self.run_session("2", "1", "bits", "1", "Binary", "6", "1", "An answer", "/quit")
        answers = [call for call in backend.calls if call[0] == "review.answer"]
        self.assertEqual(answers[0][2]["topic"], "Binary")

    def test_job_action_uses_selected_job(self):
        _, backend, _ = self.run_session("8", "2", "demo-job", "3", "/quit")
        retry = [call for call in backend.calls if call[0] == "jobs.retry"]
        self.assertEqual(retry[0][2]["job"], "demo-job")

    def test_eof_and_keyboard_interrupt_exit_cleanly(self):
        _, _, output = self.run_session()
        self.assertIn("Exiting stub session", output)
        def interrupt(prompt):
            raise KeyboardInterrupt
        output = []
        Session(StubAPI(), read=interrupt, write=output.append).run()
        self.assertIn("Exiting stub session", "\n".join(output))


if __name__ == "__main__":
    unittest.main()
