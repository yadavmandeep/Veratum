Run this Veratum request and show the result: {{ARGS}}

Use the shell. `V` below means `python3 .veratum/engine/veratum_cli.py`. Every request has the form `<area> <action> [arguments]`. Match it against this table (first words decide):

| Request | Run |
|---|---|
| `graph build` | `V graph build`, then `V graph report` and give a 5-line summary (size, biggest areas, most connected code, anything AMBIGUOUS worth a look). If it says the file limit was reached, re-run with `--max-files 20000` |
| `graph query <question>` | `V graph query "<question>"` |
| `graph report` | `V graph report`, then give a 5-line summary |
| `graph export` | `V graph export`, then say where the files are (`.veratum/graph/export/`: `graph.html`, `graph.svg`, `obsidian/`, `graph.cypher`) |
| `graph path <A> <B>` · `graph explain <name>` | `V graph path <A> <B>` · `V graph explain <name>` |
| `graph status` | `V graph status` |
| `graph watch` | tell the user to run `V graph watch` in a terminal (it keeps running) |
| `graph docs` | `V graph semantic list`; then read each listed file and store what you learned with `V graph semantic add --data '{"source_file":"<file>","nodes":[{"label":"..."}],"edges":[{"source":"..","target":"..","relation":".."}]}'` |
| `impact <file>` | `V impact <file> --evidence` |
| `status` (or empty) | `V status` |
| `gate` | `V gate` |
| `doctor` | `V doctor` |
| `memory` | `V brain show` |
| `remember <fact>` | `V remember "<fact>"` |
| `config` · `config <name> <value>` | `V config` · `V config <name> <value>` (for example `config graph_auto off`) |
| anything else, e.g. `where is login handled?` | treat it as `graph query "<the request>"` |

If `.veratum/` does not exist yet, tell the user to install first: `npx github:yadavmandeep/Veratum init --ide <their-ide>`.

Rules: do not edit project files for these requests. Quote the output you got and name the files and lines it points to. If a command fails, show the error instead of guessing. Lines marked `INFERRED` or `AMBIGUOUS` are name matches: open the cited line before relying on them.
