import { test } from "node:test";
import assert from "node:assert/strict";
import { parseArgs } from "../src/args.ts";

test("flags and files", () => {
  assert.deepEqual(parseArgs(["-v", "--out", "x.txt", "a", "b"]), {
    verbose: true,
    out: "x.txt",
    format: "text",
    files: ["a", "b"],
  });
});

test("format", () => {
  assert.equal(parseArgs(["--format", "json"]).format, "json");
  assert.throws(() => parseArgs(["--format", "xml"]), /format/);
});
