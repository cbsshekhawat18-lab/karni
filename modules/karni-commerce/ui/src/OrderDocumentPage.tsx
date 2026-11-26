/**
 * An order's printable document, an invoice or a packing slip
 * (`GET /orders/document/`). The server answers a whole HTML page, shown here
 * in a frame so its own styles stay apart from the app's.
 */
import {
  Button,
  ErrorState,
  KarniApiError,
  Skeleton,
  useKarniClient,
  usePageMeta,
} from "@karni/ui";
import { useQuery } from "@tanstack/react-query";
import { useRef } from "react";
import { CommerceLink, useCommerce } from "./routes";

export interface OrderDocumentPageProps {
  number: number | string;
  /** The guest's key (the `key` search value). */
  orderKey?: string;
  kind?: "invoice" | "packing_slip";
  title?: string;
}

export function OrderDocumentPage({
  number,
  orderKey = "",
  kind = "invoice",
  title,
}: OrderDocumentPageProps) {
  const client = useKarniClient();
  const { paths, navigate } = useCommerce();
  const frame = useRef<HTMLIFrameElement>(null);
  const heading = title ?? (kind === "invoice" ? "Invoice" : "Packing slip");
  usePageMeta({ title: `${heading} for order ${number}` });
  const html = useQuery<string>({
    queryKey: ["karni-commerce", "document", String(number), orderKey, kind],
    queryFn: async ({ signal }) => {
      const response = await client.requestRaw("/orders/document/", {
        query: { number, key: orderKey, kind },
        signal,
      });
      return response.text();
    },
  });
  if (html.isPending) return <Skeleton className="h-96 w-full" />;
  if (html.isError) {
    const missing = html.error instanceof KarniApiError && html.error.status === 404;
    const back = <CommerceLink to={paths.order(number, orderKey)}>Back to the order</CommerceLink>;
    return missing ? (
      <div className="space-y-2">
        <p role="alert">No such order.</p>
        {back}
      </div>
    ) : (
      <ErrorState error={html.error} onRetry={() => void html.refetch()} actions={back} />
    );
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 print:hidden">
        <Button onClick={() => frame.current?.contentWindow?.print()}>Print</Button>
        <Button variant="outline" onClick={() => navigate(paths.order(number, orderKey))}>
          Back to the order
        </Button>
      </div>
      <iframe
        ref={frame}
        title={`${heading} for order ${number}`}
        srcDoc={html.data}
        sandbox="allow-same-origin allow-modals"
        className="min-h-[80vh] w-full rounded-lg border border-border bg-white"
      />
    </div>
  );
}
