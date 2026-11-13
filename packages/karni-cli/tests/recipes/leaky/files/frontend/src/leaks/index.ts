// The leaky part's frontend reaches into the CRM part's folder.
import { deals } from "../crm/deals";

export function register(): void {
    deals();
}
