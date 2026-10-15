# Review of src/rateLimiter.ts

- `allow`: `elapsed` is in milliseconds (`Date.now`) but is multiplied by `ratePerSecond`, so buckets refill 1000x too fast. Divide by 1000.
- `allow`: tokens are never capped at `capacity` (missing `Math.min`), so an idle client accumulates an unbounded burst.
- `buckets` is a plain object keyed by user input: a key like `__proto__` or `constructor` hits the prototype. Use a `Map`.
