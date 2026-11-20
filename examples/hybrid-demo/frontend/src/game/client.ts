// The game's data client inside the app: its calls go through the app's own API client,
// so a member plays as their account (the app's sign-in is the game's). Each account
// keeps its own copy on the device, in case two members share it.
import { createGameClient, createStorage, type GameClient } from "@karni/game";
import { useAuth, useKarniClient } from "@karni/ui";
import { useEffect, useMemo } from "react";

export const GAME = "tile-match";

export function useGameClient(): GameClient {
    const transport = useKarniClient();
    const user = useAuth().user;
    const account = user === null ? "visitor" : String(user.id);
    const client = useMemo(
        () =>
            createGameClient({
                game: GAME,
                storage: createStorage({ namespace: `${GAME}.${account}` }),
                server: { transport, signedIn: () => account !== "visitor", path: "/api/game/" },
            }),
        [transport, account],
    );
    useEffect(() => () => client.destroy(), [client]);
    return client;
}
