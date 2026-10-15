// Hidden validator for a review task: REVIEW.md must identify the planted
// units bug plus at least one more planted issue; the source must be untouched.
// Keyword rubrics are a coarse proxy for review quality; see benchmarks/README.md.
import { existsSync, readFileSync } from "node:fs";

const ISSUES = {
  units: [/1000/, /milli/i, /\bms\b/i, /\bunits?\b/i],
  cap: [/Math\.min/, /\bcap(ped|ping)?\b/i, /exceed(s|ing)? (the )?capacity/i, /unbounded/i, /overflow/i],
  proto: [/__proto__/, /prototype/i, /\bMap\b/],
};
const REQUIRED = ["units"];
const MIN_FOUND = 2;

const failures = [];
if (!existsSync("REVIEW.md")) {
  console.log("FAIL: REVIEW.md missing");
  process.exit(1);
}
const review = readFileSync("REVIEW.md", "utf8");
const found = Object.entries(ISSUES)
  .filter(([, pats]) => pats.some((p) => p.test(review)))
  .map(([k]) => k);
console.log("issues found:", found);
for (const r of REQUIRED) if (!found.includes(r)) failures.push(`missing required issue: ${r}`);
if (found.length < MIN_FOUND) failures.push(`found ${found.length} planted issues, need ${MIN_FOUND}`);

const norm = (s) => s.replace(/\r\n/g, "\n");
const current = norm(readFileSync("src/rateLimiter.ts", "utf8"));
const original = norm(readFileSync("__hidden__/original_rateLimiter.ts", "utf8"));
if (current !== original) failures.push("src/rateLimiter.ts was modified during a review-only task");

for (const f of failures) console.log("FAIL:", f);
if (!failures.length) console.log("PASS");
process.exit(failures.length ? 1 : 0);
