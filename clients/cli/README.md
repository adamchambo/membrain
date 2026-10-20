# Interactive navigation prototype

Run from `clients/cli`:

```sh
python3 -m oracle_cli
```

This is **local stub mode**. No server or AI is contacted, no files are saved,
and entered text exists only in memory until exit. Fixed demo candidates are
navigation examples, not assessments of your knowledge. The wizard is still a stub.

Choose numbered menu entries. `0` goes back in menus and exits at the main menu.
`/back`, `/menu`, and `/quit` work at any prompt. During capture, `/show` and `/undo`
call placeholder handlers. Review and gap diagnostics accept an answer before
showing placeholder feedback. There is no background-job polling yet.

`session.py` owns the loop and navigation stack; `menus.py` defines screens;
`stub_api.py` records named calls in memory. Input and output are injected so the
flow can be tested without an interactive terminal. Existing command and wizard
stubs remain available for later extraction and API wiring.

Run navigation tests from `clients/cli`:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_session.py'
```

The package defines an `oracle` console entry point for a later package install.
No installation is required for the module command above.

---

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
