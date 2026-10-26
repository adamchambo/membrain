# Membrain CLI

The CLI connects to the local FastAPI server through the generated Python SDK.
No client authentication is used. LLM provider keys are stored in the server's
application settings, never in CLI state.

## Install and run

From the repository root, using Python 3.10+ (the existing project venv uses 3.12):

```sh
.venv/bin/python -m pip install -e sdk/python -e clients/cli
.venv/bin/membrain
.venv/bin/membrain menu
.venv/bin/membrain setup
.venv/bin/membrain --stub
```

- `membrain` opens the conversation (see below), resuming the last one for this
  server. `membrain menu` opens the classic menus instead. First launch or an unready
  database opens setup automatically; setup can also be opened with `/setup` during a session.
- Model setup first offers Local model (Ollama or LM Studio), Cloud provider
  (OpenAI or another compatible provider), or Custom endpoint. Local addresses
  are prefilled and editable; available local model IDs are offered for selection,
  with manual entry when listing is unavailable. Chat profiles include standard
  behavior and an explicit Qwen3 fast mode; other models retain their normal prompts. Local runtimes
  must already be running with the model installed. Provider menus accept `0` to
  return without saving. Embeddings retain explicit vector-profile settings.
- `setup` configures an already running server. It selects the server address,
  reads readiness, and offers chat, embedding, database and validation settings.
- `--stub` runs explicit demo responses without API requests or saved CLI state.
- `--api-url URL` selects the server address, overriding `MEMBRAIN_API_URL` and the
  last saved address. The default is `http://127.0.0.1:8000`.
- `--no-setup` skips automatic setup and uses the existing server settings.

Use the root `./start` launcher for persistent services, or manage the API, database
and worker separately using the root README's server or Compose instructions. The wizard doesn't install services. Database switching and
migrations use the server setup command `python -m app.setup --migrate` from
`server/`, with the server environment loaded. A stopped worker doesn't prevent
raw capture when the database is ready, but organization and learning wait for it.

The wizard updates one capability without clearing omitted settings. Explicitly
disabling a capability sends null. Nonempty server environment variables override
file settings; the wizard reports overrides returned by setup. Existing embeddings
use the server's profile migration: old vectors stay active until explicit cutover.
Provider keys are entered without terminal echo and submitted only to server settings.

## Conversation

Type naturally. The server interprets each message and runs the matching activity;
there are no menus or prerequisites to choose first:

- "I'm learning about LLMs. I think attention lets tokens weigh each other." saves
  your explanation in your words and files it under a subject automatically.
- "Remind me how fractions work using my pizza analogy" quotes what you saved, then
  separately says what holds up and where it breaks down. Your saved words never change.
- "What gaps do I have about maths?" or "Pick a gap from anything I've learned"
  names suspected misconceptions (labelled as suspicions) and, for a subject, topics
  with nothing saved that sit between ones you do have. It asks one check question.
- "Give me cue cards for what I learned recently" ("recently" = 7 days) or
  "A multiple-choice quiz on binary from last week" (calendar week, your timezone).
  Answer with a letter or your own words; `stop` ends the set.
- "Explain two's complement with a diagram" teaches without saving; "save that"
  adopts it as your explanation, recorded as adopted rather than your own words.

Each message is saved on the server before any model call, with a client message ID,
so a network failure followed by `/retry` cannot save it twice. While Membrain works,
progress lines appear; Ctrl-C returns to the prompt and the reply arrives later as a
background result. A failed message shows what did complete (for example what was
saved) and `/retry` reprocesses only the unfinished part. Your timezone comes from
`TZ` or `/etc/localtime`.

Chat commands: `/new` starts a conversation, `/history` shows recent turns, `/undo`
retracts what your last message saved, `/map` opens a 3D view of saved explanations
(the conversation's subject, or the whole bank when it has at most 100 concepts),
`/menu` opens the classic menus (`/chat` or "Back to the conversation" returns),
`/help`, `/quit`.

## Navigation and learning

The main menu includes Settings / setup and Help. `/help` displays commands at
any session prompt; menus also accept `help`, `--help`, `-h` and `?`. From the shell,
`membrain --help` lists startup options and `membrain setup` opens configuration.

Use ↑/↓ to highlight a menu option and Enter to select it. Numbers and slash
commands still work. Redirected input/output uses plain numbered menus. `0` returns in submenus; `x` exits at the main menu.
`/back`, `/menu`, `/quit`, `/jobs` and `/setup` work at prompts. `/more` advances
paged listings. Choices display real IDs and accept either a result number or UUID.

Capture saves each message immediately. `/show` inspects the last capture, `/undo`
retracts its derived changes, and `/history` displays the current conversation's
history. Network failures leave input in memory; `/retry` reuses the original capture
request ID. Exiting discards unsaved draft text. Confirmed messages stay on the server.

Explore offers text search, concepts, subjects, resources, recents and timeline.
Concept views can open related concepts, revision history, review, clarification,
new explanation revisions, resource attachment and archiving. Stored resource
content is displayed when available; a bookmark does not fetch external content.

Review supports a concept or explicit subject scope, with cue cards, teach-back,
missing steps, application and mixed quizzes. The question appears before an answer;
answers save before feedback processing. Unfinished reviews can be resumed from
the review menu without revealing the saved explanation before answering. Feedback compares recall with the saved
understanding and does not establish factual correctness or mastery.

Gap discovery can use a selected scope, a recent recorded concept, or a random
concept from the newest 100. Candidates explain their evidence. Inspect the result,
select a suggestion, then answer its diagnostic question. The answer is saved as a
capture before a separate clarification task discusses it. A possible gap remains
unestablished; absent records don't prove missing knowledge. Adopting or dismissing
a suggestion requires your explicit recorded decision. Marking familiar without
an explanation doesn't create assessed mastery.

A new clarification question can start without a saved concept. Its generated
answer and follow-on teaching stay separate from banked understanding.

Short lessons, worked examples and textual diagrams remain generated artifacts,
separate from your own understanding. New explanations are saved only through capture
or an explicit explanation revision. Reflection accepts subjects and/or timezone-aware
ISO time intervals and shows recorded review coverage, not inferred mastery.

## Background work and local state

A worker thread polls known job IDs with bounded HTTP timeouts. It queues output;
interactive prompts redraw safely when results arrive, preserving any typed draft.
Redirected/scripted input still prints results between prompts. The
server keeps processing after the CLI exits. Completed jobs remain inspectable
without replaying their completion notifications at the next launch. Learning and review results can also
be inspected through their job IDs in Processing status.

Processing status lists the most recent 100 jobs seen by this client, not every job
on the server (there is no global job-list endpoint). A different known job UUID can
be pasted to inspect its work record. Completed learning results restore their scope
from server provenance. Scope limits are shown as errors so users can narrow a subject.

Client state contains only server addresses, conversation/capture IDs and job IDs.
It is stored per server in `$XDG_STATE_HOME/membrain/cli.json`, defaulting to
`~/.local/state/membrain/cli.json`, with mode 0600. `MEMBRAIN_CLI_STATE_FILE` overrides the
file path, useful for tests or separate installations. It stores no provider keys,
explanation text or diagnostic answers.

## Implementation and checks

`types.py` defines typed context/results and the backend protocol. `api.py` owns SDK
connections and safe error conversion; `commands/` contains feature handlers.
`session.py` handles menus and typed state transitions. `jobs.py` polls without terminal
IO; `output.py` renders results. `wizard/` reuses the setup API. `stub_api.py` alone
contains navigation fixtures, selected only through explicit stub mode.

```sh
.venv/bin/python -m unittest discover -s clients/cli/tests -v
```

`server/tests/test_cli.py` additionally exercises SDK → FastAPI → disposable
PostgreSQL → worker journeys, including a real loopback HTTP request. Use the guarded
server test runner described in `server/tests/README.md`. AI responses in these tests
are injected; real-model quality and full Docker startup are separate acceptance work.

The original `clients/cli/membrain.py` script remains available for its existing direct
commands. The installed `membrain` command is the interactive client documented here.

Clarification uses the previous generated result as conversational context, not
banked knowledge. Follow-ups wait until that result is ready. Saving your own
explanation afterwards creates a new capture when no concept is selected.

Search defaults to hybrid when embeddings are configured; exact text and meaning
modes are available in Explore. Meaning-search failures fall back to text with a
message. Archived concepts can be browsed and restored. The subject menu can add
concepts to a subject created from Explore. Reflection history first asks which
changed concept to inspect.
