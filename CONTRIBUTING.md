# Contributing to Veratum

Thank you for your interest in contributing to Veratum! We welcome bug reports, feature proposals, documentation improvements, benchmark tasks, and code contributions.

Veratum is an open-source engineering harness designed to make AI coding agents reliable, truthful, and evidence-backed. As a contributor, you are helping build the standard for trustworthy AI engineering.

---

## Code of Conduct

All contributors and participants are expected to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md). Please report any unacceptable behavior via GitHub repository moderation or maintainer contact on GitHub.

---

## How to Contribute

### 1. Reporting Issues & Requesting Features
- **Bug Reports**: Open an issue detailing the unexpected behavior, steps to reproduce, agent/IDE environment, model used, and operating system.
- **Feature Proposals**: Describe the user story, proposed command/API design, and the rationale before submitting a large PR.

### 2. Developing Veratum Locally

Veratum requires **Node.js (>=16)** and **Python (>=3.8)**.

#### Prerequisites
- Node.js (Node 22.6+ recommended for running benchmark TypeScript fixtures)
- Python 3.8+ (no third-party dependencies; Veratum's engine uses standard libraries)
- Git

#### Build & Code Generation
When editing core specifications or the engine, synchronize adapters and skill files:

```bash
# Rebuild skill packages and IDE adapter files from core/SKILL.template.md
node bin/veratum.js build

# Validate that generated adapters and skills are strictly in sync
node bin/veratum.js build --check
```

#### Running the Test Suite
Before opening a PR, ensure all tests pass:

```bash
npm test
```
This runs the sync check followed by the Python engine unittest suite (`python -m unittest discover -s tests -v`).

---

## Pull Request Guidelines

1. **Follow the 6-Gate Protocol**: If developing with an AI assistant in this repository, ensure your agent operates through Veratum contracts and gates.
2. **Minimal & Scoped Changes**: Only modify files relevant to your issue or feature. Avoid drive-by refactorings.
3. **Zero External Dependencies**: Veratum's engine runtime is zero-dependency. Do not add external third-party dependencies to `engine/` or core skills unless explicitly approved.
4. **Comprehensive Tests**: Add corresponding test coverage in `tests/test_veratum_engine.py` for any new engine features or edge cases.
5. **Clear Commit Messages**: Use Conventional Commits formatting:
   - `feat: ...` for new features
   - `fix: ...` for bug fixes
   - `docs: ...` for documentation changes
   - `test: ...` for test additions or updates

---

## License

By contributing to Veratum, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).
