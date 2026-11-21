import type { ShopItem } from "@karni/game";
import type { Scene } from "@karni/game/scenes";
import type { DialogHandle } from "@karni/game/ui";
import { COSMETICS } from "../palette";
import type { GameServices } from "./services";

/** One row: a swatch, the name and price, and Buy, Wear or Wearing. */
function row(item: ShopItem, coins: number, act: (item: ShopItem) => void): HTMLLIElement {
    const li = document.createElement("li");
    const swatch = document.createElement("span");
    swatch.className = "sd-swatch";
    const colors = COSMETICS[item.key]?.colors ?? ["#888888"];
    swatch.style.background = colors.length > 1 ? `linear-gradient(135deg, ${colors.join(", ")})` : (colors[0] ?? "");
    swatch.setAttribute("aria-hidden", "true");
    const name = document.createElement("span");
    name.className = "sd-name";
    const price = item.price ? `${item.price.amount} coins` : "";
    name.textContent = `${item.title} (${item.slot ?? "item"})${item.owned ? "" : `, ${price}`}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "kg-btn";
    button.dataset.item = item.key;
    if (item.equipped) {
        button.textContent = "Wearing";
        button.disabled = true;
    } else if (item.owned) {
        button.textContent = "Wear";
    } else {
        button.textContent = "Buy";
        button.disabled = !item.price || item.price.amount > coins;
    }
    button.addEventListener("click", () => act(item));
    li.append(swatch, name, button);
    return li;
}

/**
 * The shop: trails and hats for coins, a daily gift and coins for an ad. The prices and the
 * balance are the server's: the client asks to buy an item by its key and never names an amount.
 */
export function createShopScene(_hooks: unknown): Scene<GameServices> {
    let dialog: DialogHandle | null = null;
    return {
        name: "shop",
        overlay: true,
        enter({ services, stack }) {
            const session = services.run.session;
            const body = document.createElement("div");
            const balance = document.createElement("p");
            const list = document.createElement("ul");
            list.className = "sd-list";
            const extras = document.createElement("div");
            extras.className = "kg-actions";
            body.append(balance, list, extras);
            const render = async (): Promise<void> => {
                if (!session) return;
                const items = await session.shop();
                balance.textContent = `You have ${session.coins()} coins.`;
                list.replaceChildren(...items.map((item) => row(item, session.coins(), act)));
            };
            const act = (item: ShopItem): void => {
                if (!session) return;
                const work = item.owned ? session.equip(item.key) : session.buy(item.key);
                void work
                    .then(() => {
                        services.sfx.play(item.owned ? "land" : "buy");
                        if (item.slot === "trail") services.run.useSession(session);
                        services.ui.toast(item.owned ? `Wearing ${item.title}.` : `${item.title} is yours.`);
                    })
                    .catch(() => services.ui.toast("That did not work. Check the coins and try again.", { kind: "error" }))
                    .then(render);
            };
            const extra = (id: string, label: string, run: () => Promise<string>): void => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "kg-btn";
                button.dataset.kgAction = id;
                button.textContent = label;
                button.addEventListener("click", () => {
                    button.disabled = true;
                    void run()
                        .then((message) => services.ui.toast(message))
                        .then(render)
                        .finally(() => {
                            button.disabled = false;
                        });
                });
                extras.append(button);
            };
            extra("gift", "Daily coins", async () => {
                const got = (await session?.checkIn()) ?? 0;
                return got > 0 ? `${got} coins for today.` : "Today's coins are in. Come back tomorrow.";
            });
            if (session?.portal.canShowRewarded()) {
                extra("ad-coins", "Watch an ad for coins", async () => {
                    const result = await session.adCoins();
                    return result.status === "granted" ? `${result.granted.amount} coins for the ad.` : "No coins this time.";
                });
            }
            dialog = services.ui.dialog({
                title: "Shop",
                body,
                actions: [{ id: "done", label: "Done", primary: true }],
                onClose: () => stack.pop(),
            });
            void render();
        },
        exit() {
            dialog?.close();
            dialog = null;
        },
        draw: () => undefined,
    };
}
