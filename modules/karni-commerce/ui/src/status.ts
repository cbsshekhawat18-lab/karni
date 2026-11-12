import type { OrderStatus } from "./types";

/** An order's money state in words, for its buyer. Override per project by passing `statusWords`. */
export const ORDER_STATUS_WORDS: Record<OrderStatus, string> = {
  pending: "Waiting for payment",
  paid: "Paid",
  part_paid: "Part paid",
  failed: "Payment failed",
  cancelled: "Cancelled",
  refunded: "Refunded",
  part_refunded: "Part refunded",
};
