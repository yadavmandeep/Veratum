---
name: veratum-typescript
description: Veratum stack pack for TypeScript and JavaScript projects - Node, React, Next.js, Vite, NestJS, Express. Picks the right package manager and verification commands, maps tsconfig path aliases for blast radius, and lists the TS/JS pitfalls agents repeat most.
version: 1.0.0
author: Mandeep Yadav
license: MIT
---

# Veratum × TypeScript / JavaScript

Use alongside the `veratum` skill. `V` = `python3 .veratum/engine/veratum_cli.py`.

## Commands (pin them once, reuse forever)
- Package manager from the lockfile: `pnpm-lock.yaml` → pnpm, `yarn.lock` → yarn, `bun.lock(b)` → bun, else npm. Never mix them, and never create a second lockfile.
- Pin what actually works:
  `V brain set-cmd test "<pm> test"` · `V brain set-cmd typecheck "npx tsc --noEmit"` · `V brain set-cmd lint "<pm> run lint"`
- Watch-mode runners hang the agent. Make the contracted verify one-shot: `vitest run`, `jest --ci`, `CI=1 <pm> test`.
- Contract verify for most changes: `"<pm> run typecheck && <pm> test -- <related tests>"`. Type errors are failures, not warnings.

## Blast radius
- `V impact` resolves relative imports, `index.ts` barrels and `@/`/`~/` aliases by path suffix. With custom `paths` in `tsconfig.json`, also grep the alias name for the module.
- A barrel (`index.ts`) re-export puts every importer of the barrel in the radius. Check `V impact src/<dir>/index.ts` too.

## Pitfalls to avoid
- Don't silence types with `any`, `as unknown as`, `@ts-ignore`, `!` non-null assertions or `eslint-disable` to get green.
- ESM/CJS: keep the file's existing module style. In ESM TS projects relative imports may need `.js` extensions.
- React: hooks rules, stable keys, no state updates during render. Next.js: respect the server/client component boundary (`"use client"`), and never import server-only code into client components.
- Don't upgrade dependencies or touch `package.json`/lockfile unless the contract includes them.
- Snapshot tests: update snapshots only when the change was intended, and say so in the evidence.

Record repo-specific quirks: `V remember "<quirk>" --kind pitfall`.
