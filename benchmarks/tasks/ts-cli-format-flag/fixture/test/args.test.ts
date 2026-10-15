import { test } from "node:test";
import assert from "node:assert/strict";
import { parseArgs } from "../src/args.ts";

test("flags and files", () => {
  assert.deepEqual(parseArgs(["-v", "--out", "x.txt", "a", "b"]), {
    verbose: true,
    out: "x.txt",
    files: ["a", "b"],
  });
});
