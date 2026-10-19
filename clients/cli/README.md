# CLI client

A small standard-library Python client that calls the FastAPI server. Start the API
and worker first; AI configuration remains on the server.

```sh
python3 clients/cli/oracle.py chat
python3 clients/cli/oracle.py chat --new
python3 clients/cli/oracle.py capture "I'm learning about computers"
python3 clients/cli/oracle.py review CONCEPT_UUID
```

`chat` resumes the last conversation on this device. Say what you understand and
receive a brief saved acknowledgement; background processing handles organization.
`--new` starts fresh; `--conversation UUID` resumes a particular conversation.
`capture` saves its `text` argument as one message, with an optional conversation UUID.
`review` takes the concept UUID to assess and runs one cue card; feedback compares
recall with the saved explanation and does not verify factual correctness.

Inside chat, `/show` displays the last capture's understanding and optional questions,
`/undo` retracts its latest derived explanations, `/new` starts a new topic, and
`/quit` exits. Original messages and revision history remain available. Undoing an
older capture with later dependent explanations requires editing the current
understanding instead.

`--api-url` selects the server, defaulting to `ORACLE_API_URL` or
`http://127.0.0.1:8000`. This client stores only the last receipt's IDs under
`$XDG_STATE_HOME/oracle/` (default `~/.local/state/oracle/`), separately for each API
URL. It has no database connection or model credentials.
