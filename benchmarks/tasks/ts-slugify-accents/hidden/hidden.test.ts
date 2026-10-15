import { test } from "node:test";
import assert from "node:assert/strict";
import { slugify } from "../src/slugify.ts";

test("diacritics are transliterated", () => {
  assert.equal(slugify("Crème Brûlée"), "creme-brulee");
  assert.equal(slugify("Café Münster"), "cafe-munster");
  assert.equal(slugify("ÅNGSTRÖM über"), "angstrom-uber");
  assert.equal(slugify("naïve façade"), "naive-facade");
});

test("existing behaviour kept", () => {
  assert.equal(slugify("Hello World"), "hello-world");
  assert.equal(slugify("---a---"), "a");
  assert.equal(slugify("C++ & Rust: 2024!"), "c-rust-2024");
  assert.equal(slugify(""), "");
  assert.equal(slugify("日本"), "");
});
