import { test } from "node:test";
import assert from "node:assert/strict";
import { slugify } from "../src/slugify.ts";

test("basic titles", () => {
  assert.equal(slugify("Hello World"), "hello-world");
  assert.equal(slugify("  Already--slugged  "), "already-slugged");
});
