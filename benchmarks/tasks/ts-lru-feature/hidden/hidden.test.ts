import { test } from "node:test";
import assert from "node:assert/strict";
import { LRUCache } from "../src/lru.ts";

test("get refreshes recency", () => {
  const c = new LRUCache<string, number>(2);
  c.set("a", 1).set("b", 2);
  assert.equal(c.get("a"), 1);
  c.set("c", 3);
  assert.equal(c.has("a"), true);
  assert.equal(c.has("b"), false);
});

test("peek does not refresh recency", () => {
  const c = new LRUCache<string, number>(2);
  c.set("a", 1).set("b", 2);
  assert.equal(c.peek("a"), 1);
  assert.equal(c.peek("zzz"), undefined);
  c.set("c", 3);
  assert.equal(c.has("a"), false);
});

test("delete and size", () => {
  const c = new LRUCache<string, number>(3);
  assert.equal(c.size, 0);
  c.set("a", 1).set("b", 2);
  assert.equal(c.size, 2);
  assert.equal(c.delete("a"), true);
  assert.equal(c.delete("a"), false);
  assert.equal(c.size, 1);
  c.set("b", 20);
  assert.equal(c.size, 1);
  assert.equal(c.get("b"), 20);
});

test("falsy values are cached and refreshed", () => {
  const c = new LRUCache<string, number>(2);
  c.set("zero", 0).set("x", 1);
  assert.equal(c.get("zero"), 0);
  c.set("y", 2);
  assert.equal(c.has("zero"), true);
  assert.equal(c.has("x"), false);
});

test("existing behaviour kept", () => {
  const c = new LRUCache<string, number>(1);
  c.set("a", 1).set("b", 2);
  assert.equal(c.has("a"), false);
  assert.throws(() => new LRUCache(1.5), RangeError);
});
