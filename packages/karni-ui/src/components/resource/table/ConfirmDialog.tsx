/**
 * The question ResourceTable asks before destructive work (a row delete, a
 * destructive bulk action): a Modal (Radix dialog, so focus is trapped and
 * Escape cancels) naming the action and how many rows it touches. While the
 * work runs the confirm button shows progress. A failure is reported inside
 * the dialog in plain words, with the button kept for another try when
 * trying again can help. Focus returns to the control that opened it.
 * Internal to @karni/ui.
 */
import * as React from "react";
import { describeError, type KarniErrorContext } from "../../../states/describe-error";
import { ErrorState } from "../../../states/ErrorState";
import { PendingButton } from "../../../states/PendingButton";
import { Modal, ModalClose } from "../../modal/modal";
import { Button } from "../../primitives/button";

export interface ConfirmDialogProps {
  open: boolean;
  title: React.ReactNode;
  description?: React.ReactNode;
  confirmLabel: string;
  pendingLabel?: string;
  destructive?: boolean;
  pending: boolean;
  /** The last attempt's failure, shown in the dialog. */
  error?: unknown;
  errorContext?: KarniErrorContext;
  onConfirm: () => void;
  onCancel: () => void;
  /** Where focus goes when the dialog closes (the control that opened it, or a fallback). */
  returnFocus: () => HTMLElement | null;
}

export function ConfirmDialog(props: ConfirmDialogProps): React.ReactElement {
  const {
    open,
    title,
    description,
    confirmLabel,
    pendingLabel,
    destructive = false,
    pending,
    error,
    errorContext,
    onConfirm,
    onCancel,
    returnFocus,
  } = props;
  const failed = error !== undefined && error !== null;
  const retryable = !failed || describeError(error, errorContext).retryable;
  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!next && !pending) onCancel();
      }}
      title={title}
      description={description}
      contentProps={{
        onCloseAutoFocus: (event) => {
          event.preventDefault();
          returnFocus()?.focus();
        },
      }}
      footer={
        <>
          <ModalClose asChild>
            <Button variant="outline" disabled={pending}>
              Cancel
            </Button>
          </ModalClose>
          {retryable && (
            <PendingButton
              variant={destructive ? "destructive" : "default"}
              pending={pending}
              pendingLabel={pendingLabel}
              onClick={onConfirm}
            >
              {failed ? "Try again" : confirmLabel}
            </PendingButton>
          )}
        </>
      }
    >
      {failed && <ErrorState variant="inline" error={error} context={errorContext} />}
    </Modal>
  );
}
