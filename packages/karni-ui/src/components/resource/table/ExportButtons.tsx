/**
 * ResourceTable's export buttons (karni.transfer, ADR 0002 P6): one per
 * format, each downloading `GET /<resource>/export/` with the table's current
 * filters, search and ordering — the backend applies the row scope and the
 * role's field visibility, so the file is exactly what the table may show.
 *
 * Internal to @karni/ui — the public surface is ResourceTable's `exportFormats`.
 */
import * as React from "react";
import type { ResourceListParams } from "../../../hooks/types";
import { downloadResourceExport, type ExportFormat } from "../../../hooks/useResourceImport";
import { useKarniClient } from "../../../schema/provider";
import { Button } from "../../primitives/button";

export interface ExportButtonsProps {
  resource: string;
  params: ResourceListParams;
  formats: readonly ExportFormat[];
}

function describe(error: unknown): string {
  if (error instanceof Error) {
    const data = (error as { data?: unknown }).data;
    if (typeof data === "object" && data !== null && "detail" in data) {
      const detail = (data as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
    return error.message;
  }
  return "The export failed.";
}

export function ExportButtons({
  resource,
  params,
  formats,
}: ExportButtonsProps): React.ReactElement {
  const client = useKarniClient();
  const [busy, setBusy] = React.useState<ExportFormat | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const run = (format: ExportFormat): void => {
    setBusy(format);
    setError(null);
    downloadResourceExport(client, resource, params, format)
      .catch((failure: unknown) => setError(describe(failure)))
      .finally(() => setBusy(null));
  };

  return (
    <div className="flex items-center gap-2" data-testid="resource-table-export">
      {formats.map((format) => (
        <Button
          key={format}
          type="button"
          variant="outline"
          size="sm"
          disabled={busy !== null}
          onClick={() => run(format)}
          aria-label={`Export as ${format.toUpperCase()}`}
        >
          {busy === format ? "Exporting…" : `Export ${format.toUpperCase()}`}
        </Button>
      ))}
      {error !== null && (
        <span role="alert" className="text-sm text-destructive">
          {error}
        </span>
      )}
    </div>
  );
}
