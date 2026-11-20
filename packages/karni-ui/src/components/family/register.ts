/**
 * Experimental. The family's own account sections, registered once at
 * startup for the contracts the project holds. The build's
 * `frontend/src/karni/parts.ts` calls it with what karni.yaml switches on:
 *
 *   registerFamily({ people: true, notify: true });
 *
 * - `people`: "Your addresses" (`MyAddresses`) on `/account`.
 * - `notify`: "Emails and notifications" (`EmailChoices`), the person's own
 *   switches, on `/account`.
 *
 * Each part adds its own sections, tabs and tiles in its `register()`
 * (the shop's orders come from @karni/commerce-ui). Escape hatch:
 * `unregisterAccountSection("addresses")` after it, or a section of the
 * same key.
 */
import { registerAccountSection } from "../account/sections";
import { MyAddresses } from "./addresses";
import { EmailChoices } from "./inbox";

/** Experimental. Which contracts the project holds, as karni.yaml's `features` says. */
export interface FamilyContracts {
  people?: boolean;
  notify?: boolean;
}

/** Experimental. Register the account sections of the contracts the project holds. */
export function registerFamily(contracts: FamilyContracts): void {
  if (contracts.people === true) {
    registerAccountSection({
      key: "addresses",
      title: "Your addresses",
      order: 80,
      component: MyAddresses,
    });
  }
  if (contracts.notify === true) {
    registerAccountSection({
      key: "messages",
      title: "Emails and notifications",
      order: 90,
      component: EmailChoices,
    });
  }
}
