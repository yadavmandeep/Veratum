// Both modules must actually use the shared helpers (refactor, not copy).
import { readFileSync } from "node:fs";
let failed = false;
for (const f of ["src/user.ts", "src/order.ts"]) {
  const src = readFileSync(f, "utf8");
  if (!/from\s+["']\.\/validate(\.ts|\.js)?["']/.test(src)) {
    console.log(`FAIL: ${f} does not import ./validate`);
    failed = true;
  }
  if (/\[\^\s@\]\+@/.test(src)) {
    console.log(`FAIL: ${f} still contains its own email regex`);
    failed = true;
  }
}
process.exit(failed ? 1 : 0);
