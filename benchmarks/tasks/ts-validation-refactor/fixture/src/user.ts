export interface User {
  name: string;
  email: string;
}

/** Returns a list of validation errors (empty when valid). */
export function validateUser(user: User): string[] {
  const errors: string[] = [];
  if (typeof user.name !== "string" || user.name.trim().length === 0) {
    errors.push("name is required");
  }
  const email = typeof user.email === "string" ? user.email.trim() : "";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    errors.push("email is invalid");
  }
  return errors;
}
