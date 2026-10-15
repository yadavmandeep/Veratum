import { isEmail, isNonEmpty } from "./validate.ts";

export interface Order {
  id: string;
  customerEmail: string;
  items: string[];
}

/** Returns a list of validation errors (empty when valid). */
export function validateOrder(order: Order): string[] {
  const errors: string[] = [];
  if (!isNonEmpty(order.id)) {
    errors.push("id is required");
  }
  // Billing exports the raw value, so surrounding whitespace is NOT accepted here.
  if (!isEmail(order.customerEmail)) {
    errors.push("customerEmail is invalid");
  }
  if (!Array.isArray(order.items) || order.items.length === 0) {
    errors.push("items must not be empty");
  }
  return errors;
}
