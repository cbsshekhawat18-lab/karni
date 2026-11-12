// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Page, ResourceDetail } from "@karni/ui";
import { useParams } from "@tanstack/react-router";

export default function CartDetailPage() {
    const { id } = useParams({ from: "/carts/$id" });
    return (
        <Page title="Cart">
            <ResourceDetail resource="carts" id={id} />
        </Page>
    );
}
