/**
 * Experimental. What a coupon may be limited to besides items: the coupon keys
 * a selling app's adapter gives (`Sellable.coupon_keys`), such as the shop's
 * categories. An app registers each once at startup and the coupon form offers
 * a picker for it:
 *
 *     registerCouponLimit({ key: "categories", label: "Categories",
 *                           resource: "categories", labelField: "name" });
 *
 * The picker searches `resource` and keeps each row's id (the value the
 * adapter's coupon key holds) with its name.
 */
export interface CouponLimit {
  /** The coupon key (`Sellable.coupon_keys`), as `Coupon.limits` stores it. */
  key: string;
  label: string;
  /** The API resource the values come from (its rows' `id`). */
  resource: string;
  /** The row field that names a value (default `name`). */
  labelField?: string;
}

const LIMITS = new Map<string, CouponLimit>();

/** Experimental. Offer a coupon limit on the coupon form (the same key replaces it). */
export function registerCouponLimit(limit: CouponLimit): void {
  LIMITS.set(limit.key, limit);
}

/** Experimental. The coupon limits apps registered, in the order they did. */
export function couponLimits(): CouponLimit[] {
  return [...LIMITS.values()];
}
