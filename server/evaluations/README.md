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
