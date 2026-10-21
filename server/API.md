# API capabilities

| Version | Date | Change |
| --- | --- | --- |
| 0.1 | 2026-10-19 | Setup, profile migration, maintenance, sources, learning, review, maps and portability. |
| 0.2 | 2026-10-21 | Conversational turns as the primary interaction. |

FastAPI publishes request contracts in `/docs` and `/openapi.json`.
This is a local, single-bank API. Compose binds it to localhost. Account/tenant
authorization, public hosting and device sync are not implemented.

## Conversational turns

`POST /api/v1/turns` takes `text`, a client-generated `client_message_id` (UUID),
optional `conversation_id`, and an IANA `timezone`. It saves the text verbatim as a
capture and returns `202` with the turn before any model call; resubmitting the same
`client_message_id` returns the same turn, and different text with it is `409`.
Poll `GET /api/v1/turns/{id}`: `progress` is persisted (reconnecting replays it),
`status` is `processing`, `completed` or `failed`, and `reply` is plain text.
`active_question` is the conversation's pending question; multiple-choice keys are
never returned. `GET /api/v1/conversations/{id}/turns?before=&limit=` pages history.

The worker interprets a turn with one model call into up to four intents from a
closed set (bank, recall, teach, adopt, diagnose, practice, answer, stop, help),
then corrects known labelling errors deterministically. Each intent runs a fixed
server recipe; the model never chooses record IDs or tools. Topic, "this" and
period wording resolve to concept IDs on the server ("recently" is 7 days; "last
week" is the previous Monday–Sunday in the turn's timezone). Turns in a conversation
are processed in order.

Each intent's writes and its recorded effect commit in one lease-fenced
transaction, so a retried turn (`POST /api/v1/turns/{id}/retry`) skips completed
intents: nothing is banked, asked or graded twice. A failed turn's `reply` shows the
intents that did complete.

Record semantics: banking saves the user's own sentences and files them under
automatic subjects (with aliases and provenance). Teaching is stored as a learning
artifact and becomes understanding only through "save that", recorded as an adopted
suggestion revision. Recall quotes saved text verbatim and assesses it separately;
the saved explanation is never changed. Diagnosis records suspected gaps and
misconceptions as learning needs with evidence strength (`model_suspected`,
`user_uncertain`, `observed_in_answer`) and an event history; bank-wide diagnosis
ranks every saved concept deterministically before the model picks one. Practice
feedback keeps recall (versus the saved explanation) apart from factual correctness;
for multiple choice the stored key decides correctness.

## Setup and embedding profiles

- `GET /api/v1/setup`: safe configured/model flags, without credentials.
- `PUT /api/v1/setup`: full provider configuration replacement. Optional
  `database_url` is private; `database_mode` is `bundled` or `existing` PostgreSQL.
  `chat` and `embeddings` specify full endpoint URL, served model and optional key.
  Embeddings also require a profile: pinned revision, dimensions, task prefixes and
  L2 normalization. Omitted providers retain their settings; explicit null disables
  a provider. Chat also accepts `profile` (`standard` or `qwen3_fast`), `max_tokens`
  (64–8192; default 2048) and `temperature` (0–2; default 0.2).
  Environment variables still override the file; the response lists overridden keys.
- `POST /api/v1/setup/validate`: `capabilities` chooses database/chat/embeddings.
  Probes return readiness, never provider error bodies or credentials.
- `GET /health/ready`: checks migration head, recent worker heartbeat and job counts.
  Configured model flags are not live inference checks. `/health` remains liveness.
- `POST /api/v1/embedding-migrations`: target endpoint and complete profile. Returns
  an operation ID and missing current-explanation count; retries for the same running
  target reuse it. Background work populates target vectors while search keeps the
  persisted active profile. A changing bank queues both profiles.
- `GET /api/v1/embedding-migrations/{id}`: progress/status.
- `POST /api/v1/embedding-migrations/{id}/cutover`: requires zero missing current
  explanation vectors. `.../cancel` keeps the old active profile and cancels target
  embedding jobs where the target differs from the active profile. Existing vectors
  are retained; there is no automatic vector cleanup or rollback deletion.

The current local API requires no client authentication, including setup writes,
explicit probes, migration decisions, portability and permanent deletion. LLM
provider keys remain in server application settings. Archive and reference guards
still apply to deletion. Changing an existing database is an offline operation:
stop API and worker and run the setup CLI, then restart both. The CLI does not
provision an arbitrary server; start the bundled Compose database or provide an
existing PostgreSQL+pgvector connection first.

## Maintenance and provenance

`PATCH /api/v1/concepts/{id}` accepts optional `title` and `archived`.
`PATCH /api/v1/resources/{id}` accepts nullable `title`/`note` and `archived`.
`PATCH /api/v1/relationships/{id}` takes `archived` to remove/restore an edge from
active views. Archive preserves history and vectors. Explanations are edited by
adding revisions through the existing revision endpoint.

`GET /api/v1/resources` and `/conversations` use `limit` (1–100) and an opaque
`cursor`; resources also accept `include_archived`. Timeline concept filtering now
includes linked captures, bookmarks and review attempts. Recents means saved
activity; opening a page is not tracked.

`DELETE /api/v1/concepts/{id}`, `/resources/{id}` and `/captures/{id}` require prior
archive and reject **all** incoming database references, including cascades and
work records, plus learning-context references. A typical learned concept therefore
stays archived to retain its explanation history. Source versions also prevent
hard deletion of their resource. These are conservative unreferenced-record cleanup
operations, not a cascading erase-bank feature. Conversation/review-history deletion
and removal of referenced provenance are not offered.

## Source content

`POST /api/v1/resources/{id}/content` takes `media_type` (`text/plain`,
`text/markdown`, `text/html`) and `content_base64` (nonempty UTF-8, max 2 MiB).
It atomically stores an immutable version and queues extraction; identical uploads
reuse a version/job. The bookmark survives extraction failure.

`GET .../{id}/chunks` returns the latest completed version, stable chunk IDs,
ordinal, character offsets, text and source URI. Optional literal `query` filters
chunks; `limit` is 1–100. Chunks use at most 1200 characters. Older version chunks
remain stored so existing artifact citations stay meaningful. No URL fetching,
PDF/OCR, social APIs, or source-vector index is implemented. Imported text is never
automatically recorded as user understanding.

## Subjects, review and reflection

`POST /api/v1/subjects` takes `title` and optional existing `parent_id`.
`GET /subjects` lists subjects; `PUT /subjects/{id}/concepts/{id}` adds membership
idempotently. `GET /subjects/{id}/scope` exposes active concepts including descendants.

`POST /review-sessions` accepts exactly one of `subject_id` or `concept_ids`, and
`mode`: cue_card, quiz, teach_back, fill_gap, applied. The eligible set (1–200
concepts with explanations) is stored at session creation. Existing next/answer/
finish routes preserve questions, snapshot revisions and original responses.
Without conversation AI, mode-specific templates remain usable.

Selection first balances coverage within the session, then prioritizes unassessed
current revisions and actual partial/different/unclear recall feedback. Selection
evidence is retained in the question snapshot. This is not a mastery or spaced
repetition algorithm. `GET /review-sessions` lists recent history;
`GET /review-sessions/{id}` exposes snapshots/attempts (first 200 each).
`GET /reflection` accepts optional `subject_id`, timezone-aware `since` and `until`;
returns eligible/reviewed/unreviewed concepts, up to 500 revisions and attempts,
and a truncation flag. Scope is saved membership, not total knowledge of a subject.

## Learning tasks and decisions

`POST /learning-tasks` takes `kind` (clarification, suggestions, fact_check, lesson,
worked_example, diagram), 1–20 `concept_ids`, up to 10 `resource_ids`, and optional
`question`. Returns an artifact/job ID immediately. Work retrieves current and recent
user statements, selected source chunks and review evidence, then calls chat outside
the database transaction. Inputs used, output, model and prompt version are retained.
Diagram output is textual content; no graphical renderer is selected.

`GET /learning-artifacts/{id}` returns generated material, optional questions,
uncertainty, exact-quote citations, and pending suggestions. Source comparison is
labelled `sources_compared` only when matching supplied citations exist; that validates
provenance, not the truth/relevance of a model's interpretation. No web fact search
or automatic reliability rating is performed. No sources means `not_verified`.

For teaching without saved concepts, concept-change suggestions are omitted and an uncertainty note explains why; the teaching answer remains available. Scoped suggestions still require valid concept references.

Suggestions are correction, possible gap, or relationship. Gap suggestions remain
`unrecorded`/`uncertain` and require a diagnostic question. They do not establish a
deficit. `POST /learning-suggestions/{id}/decision` accepts `action` adopt/dismiss and
the user's conversational `message`. A correction creates a revision with
`user_confirmed_suggestion` origin and its suggestion reference. A relationship
creates a confirmed edge; adopting a possible gap records interest. Stale source
understanding prevents adoption. Repeating an identical decision is idempotent.

## Concept maps

`POST /concept-map` takes exactly one of `concept_ids` (max 100) or `subject_id`,
optional `include_similarity`, `minimum_similarity` (-1 to 1), and `layout`
(`none` or `circle`). It returns text-accessible nodes, confirmed edges and separately
labelled semantic candidates from compatible current-revision vectors. Pending
vectors are explicit. Circle coordinates are display placement, not an embedding
projection. 3D, prerequisites inferred from distance, and a graphical client remain
outside this first API version.

## Voice and hosted work

Voice transcription remains deferred: automatic approval review requires a selected
audio destination before allowing the transport implementation. No audio-upload API,
transcription worker, provider selection, or audio deletion was installed. Existing
text and voice-transcript capture inputs remain available.
Hosted auth, billing, email and sync remain optional future work.

## Generated SDK contract

The checked-in `contracts/openapi.json` is exported from these FastAPI routes.
See [generation tooling](../tools/codegen/README.md) for regeneration, target
selection, SDK smoke checks, and CI drift checks. Keep handwritten service
adapters outside `sdk/`. The [audit](../contracts/AUDIT.md) records typed response,
error, authentication, and generator compatibility decisions.

CLI provider updates preserve omitted settings. Explicit `chat: null` or
`embeddings: null` disables that file-configured capability; nonempty environment
values still take precedence. The CLI never reads existing provider secrets back.

Question-based clarification, lessons, examples and textual diagrams may use an
empty concept scope with a nonempty question. Gap suggestions and factual checks
still require recorded concepts. Generated answers remain learning artifacts.

## Clarification continuity and capture fidelity

Learning-task requests may include `parent_artifact_id`. A missing parent is
rejected; a pending parent returns conflict so clients can retry after completion.
The server records up to six prior turns and 12000 characters in task inputs, and
supplies them as generated conversational context. Client-supplied history fields
are not accepted. This uses the existing JSON inputs and needs no new migration.

Automatic capture explanations use complete supporting user sentences. Existing
explanations retain their wording and append new source sentences. The automatic
proposal records the applied text and labels any model paraphrase an unapplied
draft. Explicit revision endpoints retain their replacement semantics.
