# Model evaluation

`local_capture.py` uses three synthetic inputs and the installed local Ollama model.
Run it from `server/` with `PYTHONPATH=. ../.venv/bin/python evaluations/local_capture.py`.
It does not load bank data or change model configuration. Every result records schema
validity and elapsed time; successful outputs still need a person to assess fidelity.

## Observed 2026-10-19

Available local model: `qwen2.5-coder:3b-base`, served through Ollama's documented
[compatible chat endpoint](https://docs.ollama.com/api/openai-compatibility).

| Synthetic case | Valid capture result | Elapsed |
| --- | --- | --- |
| Topic introduction | No; request timed out | 45.01 s |
| Uncertain understanding | No | 12.19 s |
| Resource-only input | No | 13.58 s |

No capture result passed the schema gate. Later failures were reported as
`Unavailable`; the first run did not record their nested error types, so it does
not establish whether transport or JSON validation failed. The harness now records
the cause type for future runs. This model was not installed as Membrain's default.
No compatible embedding model was installed; embedding relevance remains untested.
Injected provider tests verify API behavior, not real-model teaching quality.

## Conversation

`live_conversation.py` sends a scripted 17-message conversation through the real turn
service and worker code: banking, analogy recall, multiple choice with the stored key,
topic and bank-wide diagnosis, teaching, adoption and time-scoped cue cards. Run it from
`server/` with `DATABASE_URL` naming a disposable, migrated `membrain_test_*` database
(the script refuses other names), optionally passing an output JSON path. Messages are
synthetic; the outputs still need a person to read them for teaching quality.

### Observed 2026-10-21

LM Studio, `oracle-chat` (Qwen3 14B, `qwen3_fast`) and `oracle-embeddings` (Nomic).

| Run | Turns completed | Total | Per turn |
| --- | --- | --- | --- |
| 1 | 17 of 17 | 421 s | 3-58 s |
| 2, after fixes | 17 of 17 | 326 s | 3-45 s |

Run 1 found routing and wording errors that are now corrected deterministically (see
`guard` in `app/conversation/interpret.py`) or by prompt changes:

- recall added to a diagnosis request, and diagnosis inferred from "I'm not sure";
- an unrelated request graded as the answer to a stale diagnostic question, and
  diagnostic answers banked as new understanding;
- "recently" narrowed to the current conversation through a spurious reference flag;
- topic recall skipping the best-matching concept because subject members came first;
- adopted teaching quoted as the user's own words, and a repeated diagnostic question;
- `saved_conflict` used for omissions, and "kind of like" analogies counted as doubt.

Run 2 confirmed those fixes. Its remaining issues were also fixed and unit tested: one
sentence split into two concepts was quoted twice, titles began "User's understanding
of", and feedback called the learner "the user". A later CLI session against a
temporary API found that "one multiple-choice question" produced three, so the count is
now parsed from the wording.

Known quality limits: most latency is the capture model writing its structured output;
with one short explanation, follow-up questions in a set can test the same example.
