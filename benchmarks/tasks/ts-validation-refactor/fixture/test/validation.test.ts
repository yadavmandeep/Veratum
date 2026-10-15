import { test } from "node:test";
import assert from "node:assert/strict";
import { validateUser } from "../src/user.ts";
import { validateOrder } from "../src/order.ts";

test("valid user", () => {
  assert.deepEqual(validateUser({ name: "Ann", email: "ann@example.com" }), []);
});

test("invalid order", () => {
  assert.deepEqual(validateOrder({ id: "", customerEmail: "nope", items: [] }), [
    "id is required",
    "customerEmail is invalid",
    "items must not be empty",
  ]);
});
