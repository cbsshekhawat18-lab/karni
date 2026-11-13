// The parcel of an order, on the staff's order page (registerOrderPanel): where it is,
// and the moves it allows now: shipped with its tracking number, then delivered. The
// buttons follow the shipment's declared row actions (x-karni-actions) when the schema
// has them, else its state. The server checks every move again.
import type { OrderPanelProps } from "@karni/commerce-ui";
import {
  Input,
  Label,
  PendingButton,
  Skeleton,
  rowActionOpen,
  useKarniClient,
  useResourceList,
  useSchema,
} from "@karni/ui";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

interface Parcel {
  id: string;
  status: "processing" | "shipped" | "delivered" | "cancelled";
  carrier: string;
  tracking_number: string;
  shipped_at: string | null;
  delivered_at: string | null;
}

const WORDS: Record<Parcel["status"], string> = {
  processing: "Being prepared",
  shipped: "Shipped",
  delivered: "Delivered",
  cancelled: "Cancelled",
};

function problemOf(error: unknown): string {
  if (error && typeof error === "object" && "data" in error) {
    const data = (error as { data: unknown }).data;
    if (data && typeof data === "object") {
      for (const value of Object.values(data as Record<string, unknown>)) {
        if (Array.isArray(value) && typeof value[0] === "string") return value[0];
        if (typeof value === "string") return value;
      }
    }
  }
  return error instanceof Error ? error.message : "Something went wrong. Try again.";
}

function ParcelMoves({ parcel, onMoved }: { parcel: Parcel; onMoved: () => void }) {
  const client = useKarniClient();
  const schema = useSchema("shipments");
  const [tracking, setTracking] = useState("");
  const [carrier, setCarrier] = useState("");
  const move = useMutation({
    mutationFn: (action: "ship" | "deliver") =>
      client.request(`/shipments/${parcel.id}/${action}/`, {
        method: "POST",
        body: action === "ship" ? { tracking_number: tracking, carrier } : {},
      }),
    onSuccess: onMoved,
  });
  const row = parcel as unknown as Record<string, unknown>;
  const canShip = rowActionOpen(schema.data, "ship", row) ?? parcel.status === "processing";
  const canDeliver = rowActionOpen(schema.data, "deliver", row) ?? parcel.status === "shipped";
  return (
    <div className="space-y-3">
      {canShip ? (
        // eslint-disable-next-line karni/no-raw-elements -- an action's input (ship/), not a model's form
        <form
          className="flex flex-wrap items-end gap-3"
          aria-label="Ship the parcel"
          onSubmit={(event) => {
            event.preventDefault();
            move.mutate("ship");
          }}
        >
          <div className="space-y-1">
            <Label htmlFor={`tracking-${parcel.id}`}>Tracking number</Label>
            <Input
              id={`tracking-${parcel.id}`}
              required
              value={tracking}
              onChange={(event) => setTracking(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor={`carrier-${parcel.id}`}>Carrier (optional)</Label>
            <Input
              id={`carrier-${parcel.id}`}
              value={carrier}
              onChange={(event) => setCarrier(event.target.value)}
            />
          </div>
          <PendingButton type="submit" pending={move.isPending}>
            Mark shipped
          </PendingButton>
        </form>
      ) : null}
      {canDeliver ? (
        <PendingButton
          variant="outline"
          pending={move.isPending}
          onClick={() => move.mutate("deliver")}
        >
          Mark delivered
        </PendingButton>
      ) : null}
      {move.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {problemOf(move.error)}
        </p>
      ) : null}
    </div>
  );
}

export function ParcelPanel({ order, refresh }: OrderPanelProps) {
  const parcels = useResourceList<Parcel>("shipments", { filters: { order: order.id } });
  if (parcels.isPending) return <Skeleton className="h-16 w-full" />;
  const rows = parcels.data?.results ?? [];
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        The parcel is made once the order is paid.
      </p>
    );
  }
  return (
    <ul className="space-y-4">
      {rows.map((parcel) => (
        <li key={parcel.id} className="space-y-2">
          <p className="text-sm">
            <span className="font-medium">{WORDS[parcel.status]}</span>
            {parcel.tracking_number
              ? `, ${parcel.carrier ? `${parcel.carrier} ` : ""}tracking ${parcel.tracking_number}`
              : ""}
            {parcel.shipped_at ? `, shipped ${new Date(parcel.shipped_at).toLocaleString()}` : ""}
            {parcel.delivered_at
              ? `, delivered ${new Date(parcel.delivered_at).toLocaleString()}`
              : ""}
          </p>
          <ParcelMoves
            parcel={parcel}
            onMoved={() => {
              void parcels.refetch();
              refresh();
            }}
          />
        </li>
      ))}
    </ul>
  );
}
