import { createPortal } from "@karni/game";
import { createPortalAdapter, gameApiUrl, portalName } from "virtual:karni-game/portal";

const portal = createPortal(createPortalAdapter());
document.title = `Tiny game on ${portalName}`;
// A portal build calls the game API on the project's own domain.
document.body.dataset.api = gameApiUrl ?? "";
void portal.init().then(() => portal.loadingFinished());
if (__KARNI_GAME_DEV__) {
  (window as unknown as Record<string, unknown>).__tinyGame = portal;
}
