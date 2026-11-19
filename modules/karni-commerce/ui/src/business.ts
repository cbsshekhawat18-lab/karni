/**
 * What the business says about itself (`GET /preferences/public/`, open to
 * visitors): its name, contact details, time zone and how money is shown.
 * It is @karni/ui's `useBusiness` (one cache for every package), kept here
 * under its old name so imports from @karni/commerce-ui keep working.
 */
export { BUSINESS_QUERY_KEY, useBusiness } from "@karni/ui";
export type { BusinessDetails } from "@karni/ui";
