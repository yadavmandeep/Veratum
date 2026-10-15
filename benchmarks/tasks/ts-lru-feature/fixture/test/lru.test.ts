import { test } from "node:test";
import assert from "node:assert/strict";
import { LRUCache } from "../src/lru.ts";

test("evicts the oldest entry", () => {
  const c = new LRUCache<string, number>(2);
  c.set("a", 1).set("b", 2).set("c", 3);
  assert.equal(c.has("a"), false);
  assert.equal(c.get("c"), 3);
});

test("rejects bad capacity", () => {
  assert.throws(() => new LRUCache(0), RangeError);
});
