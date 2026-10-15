# Publishing & launch (maintainers)

How Veratum gets onto GitHub, npm and skills.sh.

## 1. GitHub (this is also what makes skills.sh work)

```bash
git add -A
git commit -m "Veratum v1.0.0"
git remote add origin https://github.com/yadavmandeep/veratum.git
git push -u origin main
git tag v1.0.0 && git push --tags
```
The repo must be **public**. The skills CLI reads `skills/<name>/SKILL.md` straight from GitHub. **Never put a `SKILL.md` at the repo root**: the CLI checks the root first, and a root skill hides the whole `skills/` pack.

If your GitHub owner isn't `yadavmandeep`, replace `yadavmandeep/veratum` everywhere:
```bash
git grep -l "yadavmandeep/veratum" | xargs sed -i "s#yadavmandeep/veratum#<owner>/<repo>#g"
```

## 2. skills.sh

There is no submission form. skills.sh lists and ranks skills from the anonymous install telemetry of the `skills` CLI. As soon as people run
```bash
npx skills add yadavmandeep/veratum
```
the package page appears at `https://skills.sh/yadavmandeep/veratum`, with per-skill install counts. To make that happen faster:

- Install it yourself on a few real projects (each `--agent` install counts).
- Put the install line at the top of the README (done) and in every launch post.
- Use the badge: `[![skills.sh](https://skills.sh/b/yadavmandeep/veratum)](https://skills.sh/yadavmandeep/veratum)`.
- Keep each skill's `description` specific about **when** to use it. That is what users scan on skills.sh and what agents use to auto-activate it.

## 3. npm (`npx veratum`)

```bash
npm whoami                    # log in first with `npm login`
npm view veratum          # 404 = the name is free
npm test                      # sync check + test suite must pass
npm publish --access public
```
If the name is taken, publish as `@veratum/code` and update the install commands in the docs.

## 4. Release checklist

- [ ] `node bin/veratum.js build --check` passes (skills bundle + adapters in sync)
- [ ] `python -m unittest tests/test_veratum_engine.py` passes
- [ ] Version bumped in `package.json`, `pyproject.toml`, `engine/veratum_cli.py` (`VERSION`), every `SKILL.md`
- [ ] `npx skills add ./ --list` shows all 7 skills
- [ ] Fresh-project smoke test per IDE: `npx veratum init --ide <ide>` → `doctor` = 100%
- [ ] CHANGELOG / GitHub release notes

## 5. Launch ideas

- A 60-second demo: the agent "fixes" a bug, sneaks in one more edit, and the gate blocks it with `POST-VERIFICATION EDIT DETECTED`.
- A before/after token count for the log compactor on a real failing test suite.
- Publish honest measurements (task success, false "done" rate, tokens) with the setup disclosed. Developers trust numbers they can reproduce.
