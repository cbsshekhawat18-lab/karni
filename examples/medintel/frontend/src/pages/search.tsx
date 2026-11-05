import { Accordion, Button, Input, Page } from "@karni/ui";
import { useRouter } from "@tanstack/react-router";
import { useState } from "react";
import { useGlobalSearch } from "../api/hooks";

/** One query over every model that opts in, each hit under its own model's access. */
export default function SearchPage() {
    const router = useRouter();
    const [q, setQ] = useState("");
    const { data } = useGlobalSearch({ q, limit: 8 });
    const items = (data?.groups ?? []).map((group) => ({
        id: group.resource,
        title: `${group.label} (${group.hits.length})`,
        content: group.hits.map((hit) => (
            <Button key={hit.id} variant="ghost" onClick={() => router.history.push(`/${group.resource}/${hit.id}`)}>
                {hit.title} {hit.subtitle}
            </Button>
        )),
    }));
    return (
        <Page title="Search" description="Trials, companies, deals, people, brands and the two trees.">
            <Input aria-label="Search" placeholder="Search" value={q} onChange={(event) => setQ(event.target.value)} />
            <Accordion key={items.length} items={items} defaultOpen={items.map((item) => item.id)} />
        </Page>
    );
}
