"""Local demo adapter. No network, model, filesystem, or database access."""
from dataclasses import dataclass, field


@dataclass
class StubAPI:
    calls: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)

    def call(self, operation: str, text: str, context: dict[str, str]) -> str:
        """Record operation, entered text, and selected context in memory only."""
        self.calls.append((operation, text, dict(context)))
        if operation == "capture.message":
            return "[Stub] Message received in memory only. Organization/API call pending implementation."
        if operation == "review.answer":
            return "[Stub] Answer received. Feedback would compare it with saved understanding; no assessment was performed."
        if operation == "gap.answer":
            return "[Stub] Diagnostic answer received. No gap established: evidence-based assessment is not connected."
        if operation.startswith("learn."):
            return "[Stub] A generated learning artifact would appear here, separate from your recorded understanding."
        if operation in {"gap.suggest", "gap.surprise", "review.suggest"}:
            return "[Stub] Demo candidate: code execution. Fixed navigation example; no personal evidence was inspected."
        if operation == "review.finish":
            count = sum(op == "review.answer" for op, _, _ in self.calls)
            return f"[Stub] {count} review answer(s) entered during this CLI session. Actual coverage and scoring are unavailable."
        return f"[Stub] {operation}: placeholder response. No server request or persistent change."
