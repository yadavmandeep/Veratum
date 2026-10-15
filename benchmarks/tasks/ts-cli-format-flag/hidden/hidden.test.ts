import { test } from "node:test";
import assert from "node:assert/strict";
import { parseArgs } from "../src/args.ts";
import { oldParse } from "../src/legacy.ts";

test("format defaults to text", () => {
  assert.deepEqual(parseArgs(["a"]), { verbose: false, out: null, format: "text", files: ["a"] });
});

test("format json", () => {
  assert.deepEqual(parseArgs(["--format", "json", "-v", "f"]), {
    verbose: true,
    out: null,
    format: "json",
    files: ["f"],
  });
});

test("invalid format", () => {
  assert.throws(() => parseArgs(["--format", "xml"]), /format/);
  assert.throws(() => parseArgs(["--format"]), /format/);
});

test("existing behaviour kept", () => {
  assert.throws(() => parseArgs(["--nope"]), /unknown option --nope/);
  assert.throws(() => parseArgs(["--out"]), /--out needs a value/);
});

test("deprecated oldParse still exported and unchanged (external consumer)", () => {
  assert.deepEqual(oldParse("--a=1 -b  c=x"), { a: "1", b: true, c: "x" });
});
