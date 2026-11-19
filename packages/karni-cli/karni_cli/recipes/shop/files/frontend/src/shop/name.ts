// The shop's name as Settings, Details has it, else the project's name (index.html's
// title, which karni new set).
import { useSiteName } from "@karni/ui";

export function useShopName(): string {
  return useSiteName();
}
