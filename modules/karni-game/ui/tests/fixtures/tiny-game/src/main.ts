import { createPortal } from "@karni/game";
import { createPortalAdapter, portalName } from "virtual:karni-game/portal";

const portal = createPortal(createPortalAdapter());
document.title = `Tiny game on ${portalName}`;
void portal.init().then(() => portal.loadingFinished());
if (__KARNI_GAME_DEV__) {
  (window as unknown as Record<string, unknown>).__tinyGame = portal;
}
