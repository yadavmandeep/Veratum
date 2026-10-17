Run this Veratum request and show the result: {{ARGS}}

Use the shell. `V` below means `python3 .veratum/engine/veratum_cli.py`. Look at the first word of the request:

| Request | Run |
|---|---|
| empty, or `status` | `V status` |
| `doctor` | `V doctor` |
| `gate` | `V gate` |
| `report` | `V graph report` |
| `export` | `V graph export`, then say where the files are (`.veratum/graph/export/`) |
| `watch` | tell the user to run `V graph watch` in a terminal (it keeps running) |
| `impact <file>` | `V impact <file> --evidence` |
| `path <A> <B>` or `explain <name>` | `V graph path <A> <B>` or `V graph explain <name>` |
| `memory` | `V brain show` |
| `remember <fact>` | `V remember "<fact>"` |
| `docs` | `V graph semantic list`; then read each listed file and store what you learned with `V graph semantic add --data '{"source_file":"<file>","nodes":[{"label":"..."}],"edges":[{"source":"..","target":"..","relation":".."}]}'` |
| anything else (a question such as `where is login handled?`) | `V graph query "<the request>"` |

Rules: do not edit project files for these requests. Quote the output you got and name the files and lines it points to. If a command fails, show the error instead of guessing.
