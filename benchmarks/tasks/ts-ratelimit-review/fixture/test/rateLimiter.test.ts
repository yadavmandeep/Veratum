import { test } from "node:test";
import assert from "node:assert/strict";
import { RateLimiter } from "../src/rateLimiter.ts";

test("allows up to capacity in a burst", () => {
  const rl = new RateLimiter(2, 1, () => 0);
  assert.equal(rl.allow("a"), true);
  assert.equal(rl.allow("a"), true);
  assert.equal(rl.allow("a"), false);
});
