/**
 * <ReportButton>: one click requests the PDF report of a row and downloads it when ready.
 *
 * Experimental. Click → `useReport().request()`. A file ready at the current
 * cache key downloads at once. Otherwise the button says it is preparing the
 * file, follows the status, and downloads it as soon as it is ready. A
 * failed render or a refused request (404 for a row the user may not see)
 * shows the failed label, and the next click tries again.
 *
 * Escape hatches: every @karni/ui Button prop passes through (variant, size,
 * className...). `labels` replaces the three texts, `autoDownload={false}`
 * stops after the file is ready (read it through `onReady`), `save`
 * replaces the browser download, `onError` receives what was thrown.
 */
import { Button, type ButtonProps } from "@karni/ui";
import { useEffect, useRef, useState, type ReactElement } from "react";
import type { ReportState } from "./types";
import { useReport } from "./useReport";

export interface ReportButtonLabels {
  /** Before a click, and after a download. Default "Download PDF". */
  idle: string;
  /** While the file is requested or rendering. Default "Preparing PDF...". */
  working: string;
  /** After a failure. Default "Try again". */
  failed: string;
}

export interface ReportButtonProps extends Omit<ButtonProps, "onClick" | "onError" | "children"> {
  /** The report's name, e.g. "product-sheet". */
  report: string;
  /** The row's id. */
  objectId: string | number;
  /** Download the file once it is ready. Default true. */
  autoDownload?: boolean;
  /** Milliseconds between status checks while the file renders. Default 1500. */
  pollInterval?: number;
  labels?: Partial<ReportButtonLabels>;
  /** Called once the file is ready, with the API's answer. */
  onReady?: (state: ReportState) => void;
  /** Called with what a request or a download threw (a KarniApiError for the API). */
  onError?: (error: unknown) => void;
  /** Saves the downloaded file. Default: the browser downloads it. */
  save?: (blob: Blob, filename: string) => void;
}

const DEFAULT_LABELS: ReportButtonLabels = {
  idle: "Download PDF",
  working: "Preparing PDF...",
  failed: "Try again",
};

/** Experimental. A button that requests the report of one row and downloads it when ready. */
export function ReportButton(props: ReportButtonProps): ReactElement {
  const {
    report,
    objectId,
    autoDownload = true,
    pollInterval,
    labels,
    onReady,
    onError,
    save,
    disabled,
    ...buttonProps
  } = props;
  const { state, status, isWorking, request, download } = useReport(report, objectId, {
    pollInterval,
    save,
  });
  // Set by a click: the file is delivered once for it, as soon as it is ready.
  const waiting = useRef(false);
  const [failed, setFailed] = useState(false);
  const text = { ...DEFAULT_LABELS, ...labels };

  const fail = (error: unknown): void => {
    waiting.current = false;
    setFailed(true);
    onError?.(error);
  };

  const settle = (answer: ReportState): void => {
    if (!waiting.current) return;
    if (answer.status === "ready") {
      waiting.current = false;
      onReady?.(answer);
      if (autoDownload) download().catch(fail);
    } else if (answer.status === "failed") {
      fail(new Error(answer.error));
    }
  };

  // The polled status: delivers the file the click is waiting for.
  useEffect(() => {
    if (state !== undefined) settle(state);
    // settle reads the latest props through the closure; the status drives this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  const click = (): void => {
    waiting.current = true;
    setFailed(false);
    request().then(settle, fail);
  };

  let label = text.idle;
  if (isWorking) label = text.working;
  else if (failed || status === "failed") label = text.failed;

  return (
    <Button
      data-karni-role="report-button"
      {...buttonProps}
      aria-busy={isWorking}
      disabled={disabled === true || isWorking}
      onClick={click}
    >
      {label}
    </Button>
  );
}
