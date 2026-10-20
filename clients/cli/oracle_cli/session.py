"""State-based terminal loop, independent of terminal and API implementations."""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable

from .menus import MENUS
from .stub_api import StubAPI


@dataclass
class Frame:
    screen: str
    context: dict[str, str] = field(default_factory=dict)
    prompt: str | None = None
    operation: str | None = None
    after: str | None = None


class Session:
    def __init__(self, backend: StubAPI, read: Callable[[str], str] = input,
                 write: Callable[[str], None] = print):
        """Use backend for stub calls, read for input, and write for terminal output."""
        self.backend = backend
        self.read = read
        self.write = write
        self.stack = [Frame("main")]
        self.running = True

    @property
    def current(self) -> Frame:
        return self.stack[-1]

    def push(self, screen: str, **updates: str) -> None:
        context = {**self.current.context, **updates}
        self.stack.append(Frame(screen, context))

    def ask(self, operation: str, prompt: str, after: str, **updates: str) -> None:
        context = {**self.current.context, **updates}
        self.stack.append(Frame("input", context, prompt, operation, after))

    def call(self, operation: str, text: str = "") -> None:
        self.write(self.backend.call(operation, text, self.current.context))

    def run(self) -> None:
        self.write("LOCAL STUB MODE — no API, AI, or persistent storage. Input is discarded on exit.")
        self.write("Navigation: /back, /menu, /quit. Menus also accept 0 for Back (Exit at main).")
        while self.running:
            self.render()
            try:
                value = self.read("> " if self.current.prompt else "Choose: ")
            except (EOFError, KeyboardInterrupt):
                self.write("\nExiting stub session.")
                break
            self.handle(value)

    def render(self) -> None:
        frame = self.current
        if frame.prompt:
            self.write("\n" + frame.prompt)
            return
        menu = MENUS[frame.screen]
        self.write("\n" + menu.title)
        if frame.context:
            self.write("Context: " + ", ".join(f"{key}={value}" for key, value in frame.context.items()))
        for number, (label, _) in enumerate(menu.choices, 1):
            self.write(f"{number}. {label}")
        self.write("0. " + ("Exit" if frame.screen == "main" else "Back"))

    def handle(self, value: str) -> None:
        command = value.strip()
        if command == "/quit":
            self.running = False
            self.write("Exiting stub session.")
            return
        if command == "/menu":
            self.stack = [Frame("main")]
            return
        if command == "/back" or (command == "0" and not self.current.prompt):
            if len(self.stack) > 1:
                self.stack.pop()
            elif command == "0":
                self.running = False
                self.write("Exiting stub session.")
            return
        if command in {"/show", "/undo"} and self.current.operation == "capture.message":
            self.call("capture.inspect" if command == "/show" else "capture.undo")
            return
        if command.startswith("/"):
            self.write("Unknown command. Use /back, /menu, or /quit.")
            return
        if not command:
            self.write("Please enter a value.")
            return
        if self.current.prompt:
            self.submit(value)
            return
        choices = MENUS[self.current.screen].choices
        if not command.isascii() or not command.isdecimal() or not 1 <= int(command) <= len(choices):
            self.write("Choose one of the displayed numbers.")
            return
        target = choices[int(command) - 1][1]
        if target.startswith("@"):
            self.action(target[1:])
        else:
            self.push(target)

    def submit(self, value: str) -> None:
        frame = self.current
        self.call(frame.operation, value)
        if frame.operation == "capture.message":
            return
        context = dict(frame.context)
        if frame.operation in {"bank.select", "clarify.choose", "gap.choose", "review.subject", "review.concept"}:
            context["topic"] = value.strip()
        elif frame.operation == "review.answer":
            context["review_format"] = frame.context.get("review_format", "cue")
        elif frame.operation == "jobs.select":
            context["job"] = value.strip()
        elif frame.operation in {"chat.recent", "chat.find"}:
            context["conversation"] = value.strip()
        elif frame.operation.startswith("reflect."):
            context["reflection_scope"] = value.strip()
        self.stack[-1] = Frame(frame.after, context)
        if frame.after == "capture_input":
            self.stack[-1] = Frame("input", context,
                "Continue the conversation. /show inspects; /undo retracts derived changes (stub).",
                "capture.message")

    def action(self, operation: str) -> None:
        if operation == "capture.new":
            self.ask("capture.message", "What did you learn? Enter an explanation, question, uncertainty, or resource.",
                     "capture_input", conversation="new local demo")
        elif operation in {"chat.recent", "chat.find"}:
            self.call(operation)
            self.ask(operation, "Enter a conversation ID or label (demo selection):", "capture_input")
        elif operation == "bank.search":
            self.ask(operation, "Search query:", "bank_results")
        elif operation in {"bank.select", "bank.subjects", "bank.recents", "bank.timeline", "bank.resources"}:
            self.call(operation)
            self.ask("bank.select", "Enter a concept/resource ID or topic (demo selection):", "concept")
        elif operation in {"clarify.choose", "gap.choose", "review.subject", "review.concept"}:
            after = "clarify_next" if operation == "clarify.choose" else "gap_scope" if operation == "gap.choose" else "scope"
            self.ask(operation, "Enter the subject, topic, or concept ID:", after)
        elif operation == "clarify.start":
            self.ask(operation, "What would you like to clarify?", "clarify_next")
        elif operation == "clarify.unresolved":
            self.call(operation)
            self.ask("clarify.start", "Choose an unresolved question or describe it:", "clarify_next")
        elif operation == "clarify.explain":
            self.ask(operation, "Explain your updated understanding in your own words:", "clarify_next")
        elif operation in {"bank.attach", "bank.edit"}:
            self.ask(operation, "Enter the resource locator:" if operation == "bank.attach" else "Enter your revised explanation:", "concept")
        elif operation == "review.suggest":
            self.call(operation)
            self.push("scope", topic="code execution (demo)")
        elif operation.startswith("review.") and operation.split(".")[1] in {"cue", "teach", "steps", "apply", "mixed", "next"}:
            mode = self.current.context.get("review_format", "cue") if operation == "review.next" else operation.split(".")[1]
            questions = {
                "cue": "What do you recall about this topic?",
                "teach": "Explain this topic to someone encountering it for the first time.",
                "steps": "What intermediate steps connect the ideas in this topic?",
                "apply": "How might you apply this idea to a practical example?",
                "mixed": "Explain the idea, then describe a possible application.",
            }
            self.call("review.question")
            self.ask("review.answer", f"[Stub {mode} question] {questions[mode]}", "review_next", review_format=mode)
        elif operation == "review.finish":
            self.call(operation)
            self.stack = [Frame("main")]
        elif operation in {"gap.suggest", "gap.surprise"}:
            self.call(operation)
            self.push("gap_candidate", topic="code execution (demo)")
        elif operation == "gap.start":
            self.call("gap.question")
            self.ask("gap.answer", "[Stub diagnostic] Explain this topic and identify any step you are uncertain about.", "gap_next")
        elif operation == "gap.familiar":
            self.ask(operation, "Optionally explain what you know; enter 'skip' to mark familiar without an explanation:", "gap_next")
        elif operation.startswith("reflect."):
            prompts = {"reflect.subject": "Which subject?", "reflect.period": "Which time period?",
                       "reflect.both": "Enter the subject and time period:"}
            self.ask(operation, prompts[operation], "reflection")
        elif operation in {"jobs.pending", "jobs.failed", "jobs.completed"}:
            self.call(operation)
            self.ask("jobs.select", "Enter a job ID (demo selection):", "job")
        else:
            self.call(operation)

