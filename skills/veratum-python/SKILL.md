---
name: veratum-python
description: Veratum stack pack for Python projects - Django, FastAPI, Flask, data and CLI code. Detects the right environment and test runner, keeps verification one-shot and reproducible, and lists the Python pitfalls agents repeat most.
version: 1.0.0
author: Mandeep Yadav
license: MIT
---

# Veratum × Python

Use alongside the `veratum` skill. `V` = `python3 .veratum/engine/veratum_cli.py`.

## Environment and commands
- Use the project's environment, not the global one. In order: `uv run …` (`uv.lock`), `poetry run …` (`poetry.lock`), `.venv/bin/python` (Windows: `.venv\Scripts\python`), then `python -m …`.
- Pin what works:
  `V brain set-cmd test "uv run pytest -q"` · `V brain set-cmd typecheck "uv run mypy ."` · `V brain set-cmd lint "uv run ruff check ."`
- Run tests as modules (`python -m pytest`, `python -m unittest`) so imports resolve from the project root.
- Contract verify: run the targeted tests first, then the suite. For example `"python -m pytest -q tests/test_billing.py && python -m pytest -q"`.
- Django: `python manage.py test <app>` and `python manage.py makemigrations --check --dry-run`, so migrations can't drift.

## Blast radius
`V impact` resolves absolute (`pkg.mod`), relative (`from .mod import x`) and `from pkg import mod` imports. Dynamic imports, `importlib`, plugin entry points and string-based Django settings (`INSTALLED_APPS`, URL confs) are invisible to it, so grep the module's dotted name too.

## Pitfalls to avoid
- Don't `pip install` into the global interpreter or add dependencies the contract doesn't include. Never edit lockfiles by hand.
- No bare `except:` or `except Exception: pass` to make a test pass. No mutable default arguments.
- Keep the project's typing style. Don't add `# type: ignore` to silence mypy.
- Async: never call blocking I/O inside `async def`. Don't mix event loops in tests (use the repo's pytest-asyncio/anyio setup).
- Fix `ModuleNotFoundError` in tests by running from the root with `-m`, not by editing `sys.path`.

Record repo-specific quirks: `V remember "<quirk>" --kind pitfall`.
