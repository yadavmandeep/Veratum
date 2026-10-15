const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isNonEmpty(value: unknown): boolean {
  return typeof value === "string" && value.trim().length > 0;
}

export function isEmail(value: unknown): boolean {
  return typeof value === "string" && EMAIL.test(value);
}
