# Reconnaissance — learn the minimum, from the cheapest source first

Goal: know enough to change the code correctly, without reading the repo end to end.

## Order of sources (cheapest first)
1. **Brain**: `V brain show`. Commands, decisions, pitfalls, recent tasks. If it answers the question, stop there.
2. **Blast radius**: `V impact <file> --depth 2`. Gives dependents, which exports each one uses, the files that usually change with it (git history), related tests, and names mentioned without an import.
3. **Targeted reads**: the edit site plus ±40 lines, then one call site per *kind* of usage the impact report lists. One representative per pattern is enough; you don't need all 30 callers.
4. **Search**: grep for the symbol name, error message or config key. Reach for this only when 1–3 left a specific question open.
5. **Full-file reads**: only for files you will change, or files under 200 lines.

## Questions to answer before Gate 1
- Where is the behaviour implemented, and where is it *decided* (config, flags, dependency injection)?
- What calls it, and with what assumptions (types, nullability, ordering, side effects)?
- Which test proves it works today? If none does, you must write one.
- What would a user notice if it broke?

## Stop conditions
Stop exploring when you can write the contract: goal, exact files, verify command. Notes that would help next time go in `V remember … --kind architecture`.

## Anti-patterns
- Reading every file in a directory "for context".
- Re-reading files the brain already summarizes.
- Planning from file names alone. Read the edit site.
- Trusting comments over code.
