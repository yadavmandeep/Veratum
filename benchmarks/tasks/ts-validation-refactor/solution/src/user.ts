import { isEmail, isNonEmpty } from "./validate.ts";

export interface User {
  name: string;
  email: string;
}

/** Returns a list of validation errors (empty when valid). */
export function validateUser(user: User): string[] {
  const errors: string[] = [];
  if (!isNonEmpty(user.name)) {
    errors.push("name is required");
  }
  const email = typeof user.email === "string" ? user.email.trim() : "";
  if (!isEmail(email)) {
    errors.push("email is invalid");
  }
  return errors;
}
