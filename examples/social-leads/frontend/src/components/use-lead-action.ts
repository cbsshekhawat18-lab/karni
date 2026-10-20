// The lead pipeline's custom actions (status, convert, score, activity,
// bulk-assign) through the Karni client; the caller refreshes what it shows.
import { useKarniClient, useToast } from "@karni/ui";

export function useLeadAction() {
    const client = useKarniClient();
    const toast = useToast();
    return async (path: string, body: Record<string, unknown> = {}, done?: string) => {
        try {
            const result = await client.request(`/leads/${path}`, { method: "POST", body });
            if (done !== undefined) toast.success(done);
            return result;
        } catch {
            toast.error("That did not work. Reload and try again.");
            return null;
        }
    };
}
