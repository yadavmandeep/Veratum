import { test } from "node:test";
import assert from "node:assert/strict";
import * as v from "../src/validate.ts";
import { validateUser } from "../src/user.ts";
import { validateOrder } from "../src/order.ts";

const user = (name: unknown, email: unknown) => validateUser({ name, email } as any);
const order = (customerEmail: unknown) => validateOrder({ id: "o1", customerEmail, items: ["x"] } as any);

test("validate.ts exports the shared helpers", () => {
  assert.equal(typeof v.isEmail, "function");
  assert.equal(typeof v.isNonEmpty, "function");
  assert.equal(v.isEmail("a@b.co"), true);
  assert.equal(v.isEmail("a@b"), false);
  assert.equal(v.isNonEmpty("x"), true);
  assert.equal(v.isNonEmpty("   "), false);
});

test("user behaviour unchanged: email is trimmed", () => {
  assert.deepEqual(user("Ann", "  ann@example.com  "), []);
  assert.deepEqual(user("  ", "ann@example.com"), ["name is required"]);
  assert.deepEqual(user("Ann", "ann@"), ["email is invalid"]);
  assert.deepEqual(user(undefined, undefined), ["name is required", "email is invalid"]);
});

test("order behaviour unchanged: email is NOT trimmed", () => {
  assert.deepEqual(order("ann@example.com"), []);
  assert.deepEqual(order(" ann@example.com"), ["customerEmail is invalid"]);
  assert.deepEqual(order(42), ["customerEmail is invalid"]);
  assert.deepEqual(validateOrder({ id: "  ", customerEmail: "a@b.co", items: [] } as any), [
    "id is required",
    "items must not be empty",
  ]);
});
