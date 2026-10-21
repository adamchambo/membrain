"""Navigation definitions; targets are screen names or named local actions."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Menu:
    title: str
    choices: tuple[tuple[str, str], ...]


MENUS = {
    "main": Menu("Membrain", (
        ("Capture something I learned", "capture"),
        ("Explore my knowledge and resources", "explore"),
        ("Clarify something", "clarify"),
        ("Review or take a quiz", "review"),
        ("Find gaps and decide what to learn next", "gaps"),
        ("Reflect on my learning", "reflect"),
        ("Continue a conversation", "conversations"),
        ("Processing status", "status"),
        ("Settings / setup", "@setup"),
        ("Help", "@help"),
    )),
    "capture": Menu("Capture", (
        ("Start a new conversation", "@capture.new"),
        ("Continue a recent conversation", "conversations"),
    )),
    "explore": Menu("Explore", (
        ("Search", "@bank.search"),
        ("Browse concepts", "@bank.concepts"),
        ("Browse subjects", "@bank.subjects"),
        ("Recent additions and changes", "@bank.recents"),
        ("Learning timeline", "@bank.timeline"),
        ("Browse resources", "@bank.resources"),
        ("Archived concepts", "@bank.archived"),
        ("Choose search mode", "search_mode"),
        ("Create a subject", "@subject.create"),
    )),
    "search_mode": Menu("Search mode", (
        ("Hybrid — words and meaning", "@search.hybrid"),
        ("Exact text", "@search.text"),
        ("Meaning only", "@search.semantic"),
    )),
    "bank_results": Menu("Search results", (
        ("Select a concept or resource", "@bank.select"),
    )),
    "concept": Menu("Selected item", (
        ("Read explanation or source material", "@bank.read"),
        ("Inspect history and provenance", "@bank.history"),
        ("Explore related concepts", "@bank.related"),
        ("Attach a resource or manage the item", "manage"),
        ("Clarify", "@clarify.start"),
        ("Review", "formats"),
        ("Investigate possible gaps", "@gap.start"),
    )),
    "subject": Menu("Selected subject", (("Browse its concepts", "@bank.subject_members"), ("Review this scope", "formats"), ("Investigate possible gaps", "@gap.suggest"), ("Reflect", "@reflect.run"), ("Add a concept to this subject", "@subject.add"))),
    "resource": Menu("Selected resource", (("Read saved resource and extracted content", "@bank.read"), ("Archive resource", "@bank.archive"), ("Restore resource", "@bank.restore"))),
    "manage": Menu("Manage selected item", (
        ("Attach a resource", "@bank.attach"),
        ("Edit explanation", "@bank.edit"),
        ("Archive item", "@bank.archive"),
        ("Restore item", "@bank.restore"),
    )),
    "clarify": Menu("Clarify", (
        ("Choose an existing concept", "@clarify.choose"),
        ("Revisit an unresolved question", "@clarify.unresolved"),
        ("Ask a new question", "@clarify.start"),
    )),
    "clarify_next": Menu("Continue clarifying", (
        ("Discuss further", "@clarify.start"),
        ("Explain using familiar concepts", "@learn.familiar"),
        ("Request a worked example", "@learn.example"),
        ("Request a textual diagram", "@learn.diagram"),
        ("Save what I learned in my own words", "@clarify.explain"),
        ("Inspect proposed corrections or connections", "@suggestion.list"),
        ("Try a review question", "formats"),
    )),
    "suggestion": Menu("Selected suggestion", (
        ("Adopt explicitly", "@suggestion.adopt"),
        ("Investigate further", "@clarify.start"),
        ("Dismiss", "@suggestion.dismiss"),
    )),
    "review": Menu("Choose review scope", (
        ("Broad subject", "@review.subject"),
        ("Narrow topic or concept", "@review.concept"),
        ("Suggest a scope for me", "@review.suggest"),
        ("Resume an unfinished review", "@review.history"),
    )),
    "scope": Menu("Confirm review scope", (
        ("Use this scope", "formats"),
        ("Adjust scope", "@review.subject"),
    )),
    "formats": Menu("Choose review format", (
        ("Cue cards", "@review.cue"),
        ("Teach-back", "@review.teach"),
        ("Fill in missing steps", "@review.steps"),
        ("Applied scenarios", "@review.apply"),
        ("Mixed pop quiz", "@review.mixed"),
    )),
    "review_next": Menu("Review feedback", (
        ("Next question", "@review.next"),
        ("Clarify a difficulty", "@clarify.start"),
        ("Explore a possible gap", "@gap.start"),
        ("Finish and see session coverage", "@review.finish"),
    )),
    "gaps": Menu("Find possible gaps", (
        ("Choose a subject or concept", "@gap.choose"),
        ("Suggest an area to investigate", "@gap.suggest"),
        ("Surprise me", "@gap.surprise"),
    )),
    "gap_kind": Menu("Choose gap scope", (("Concept", "@gap.concept"), ("Subject", "@gap.subject"))),
    "capture_item": Menu("Saved capture", (("Inspect capture", "@capture.inspect"), ("Reply to an unresolved question", "@clarify.unresolved"), ("Undo derived changes", "@capture.undo"))),
    "gap_scope": Menu("Investigate selected scope", (
        ("Investigate this whole scope", "@gap.suggest"),
        ("Narrow it further", "@gap.choose"),
    )),
    "gap_candidate": Menu("Possible gap (unassessed)", (
        ("Inspect result and suggestions", "@suggestion.list"),
        ("Answer a diagnostic question", "@gap.start"),
        ("Mark familiar and optionally explain", "@gap.familiar"),
        ("Dismiss suggestion", "@suggestion.dismiss"),
        ("Pick another candidate", "gaps"),
    )),
    "gap_next": Menu("After the diagnostic", (
        ("Clarify my explanation", "@clarify.start"),
        ("Learn an intermediate concept", "learn"),
        ("Explore a proposed connection", "@bank.related"),
        ("Try another diagnostic question", "@gap.start"),
        ("Mark familiar and optionally explain", "@gap.familiar"),
        ("Dismiss suggestion", "@suggestion.dismiss"),
        ("Pick another candidate", "gaps"),
    )),
    "learn": Menu("Learning options", (
        ("Short lesson", "@learn.lesson"),
        ("Worked example", "@learn.example"),
        ("Textual diagram", "@learn.diagram"),
        ("Explain my understanding afterwards", "@clarify.explain"),
    )),
    "reflect": Menu("Reflect", (
        ("Choose a subject", "@reflect.subject"),
        ("Choose a time period", "@reflect.period"),
        ("Combine subject and period", "@reflect.both"),
    )),
    "reflection": Menu("Reflection results", (
        ("Revisit explanation changes", "@bank.history"),
        ("Inspect unresolved questions or difficulties", "@clarify.unresolved"),
        ("Review something unassessed", "review"),
        ("Choose a suggested next activity", "gaps"),
    )),
    "conversations": Menu("Continue a conversation", (
        ("Browse recent conversations", "@chat.recent"),
        ("Browse older conversations", "@chat.find"),
    )),
    "status": Menu("Processing status", (
        ("Pending or running work", "@jobs.list.pending"),
        ("Failed work", "@jobs.list.failed"),
        ("Completed work", "@jobs.list.completed"),
    )),
    "job": Menu("Selected job", (
        ("Inspect progress or failure reason", "@jobs.inspect"),
        ("Open linked capture or result", "@jobs.result"),
        ("Retry eligible work", "@jobs.retry"),
        ("Check setup readiness", "@jobs.readiness"),
    )),
}
