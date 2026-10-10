import { Button, EmptyState, registerComponentRole, useResourceList } from "@karni/ui";

registerComponentRole("tier-list", "TierList");

interface Tier {
    id: string;
    name: string;
    price: string;
}

export interface TierListProps {
    /** The event whose ticket tiers to list. */
    event: string;
    /** Called with the tier id when the visitor picks one. */
    onBook: (tier: string) => void;
}

/** The ticket tiers of one event, each with a Book button. */
export function TierList({ event, onBook }: TierListProps) {
    const tiers = useResourceList<Tier>("ticket-tiers", { filters: { event }, pageSize: 25 });
    const rows = tiers.data?.results ?? [];
    if (!tiers.isLoading && rows.length === 0) {
        return <EmptyState title="No tickets on sale yet" />;
    }
    return (
        <ul className="space-y-2">
            {rows.map((tier) => (
                <li
                    key={tier.id}
                    className="flex items-center justify-between rounded-md border p-3"
                >
                    <span>
                        {tier.name} — {tier.price}
                    </span>
                    <Button size="sm" onClick={() => onBook(tier.id)}>
                        Book
                    </Button>
                </li>
            ))}
        </ul>
    );
}
