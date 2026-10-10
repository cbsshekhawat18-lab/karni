import { Button, Page, ResourceDetail, useKarniClient, useResourceItem } from "@karni/ui";
import { useParams } from "@tanstack/react-router";
import { useState } from "react";

interface Booking {
    id: string;
    status: string;
}

export default function BookingDetailPage() {
    const { id } = useParams({ from: "/bookings/$id" });
    const client = useKarniClient();
    const booking = useResourceItem<Booking>("bookings", id);
    const [busy, setBusy] = useState(false);
    const paid = new URLSearchParams(window.location.search).get("paid") === "1";

    async function pay() {
        setBusy(true);
        const { url } = await client.request<{ url: string }>(`/bookings/${id}/pay/`, {
            method: "POST",
        });
        window.location.assign(url);
    }

    const pending = booking.data?.status === "pending";
    return (
        <Page
            title="Booking"
            description={
                paid ? "Payment received — your confirmation email is on its way." : undefined
            }
            actions={
                pending ? (
                    <Button disabled={busy} onClick={() => void pay()}>
                        Pay now
                    </Button>
                ) : null
            }
        >
            <ResourceDetail resource="bookings" id={id} />
        </Page>
    );
}
