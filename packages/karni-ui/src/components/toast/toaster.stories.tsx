import type { Meta, StoryObj } from "@storybook/react";
import * as React from "react";
import { Button } from "../primitives/button";
import { Toaster, type ToasterProps } from "./toaster";
import { useToast } from "./use-toast";

const meta = {
  title: "Support/Toast",
  component: Toaster,
  tags: ["autodocs"],
} satisfies Meta<typeof Toaster>;

export default meta;
type Story = StoryObj<typeof meta>;

function ToastDemo(props: ToasterProps): React.ReactElement {
  const { toast, success, error, info } = useToast();
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button
        variant="outline"
        onClick={() => {
          success("Event saved", { description: "Your changes are live." });
        }}
      >
        Success
      </Button>
      <Button
        variant="outline"
        onClick={() => {
          error("Save failed", { description: "The server rejected the request." });
        }}
      >
        Error
      </Button>
      <Button
        variant="outline"
        onClick={() => {
          info("Sync scheduled");
        }}
      >
        Info
      </Button>
      <Button
        variant="outline"
        onClick={() => {
          toast({
            title: "Event deleted",
            variant: "default",
            action: (
              <Button size="sm" variant="ghost">
                Undo
              </Button>
            ),
          });
        }}
      >
        With action
      </Button>
      <Toaster {...props} />
    </div>
  );
}

export const Playground: Story = {
  render: (args) => <ToastDemo {...args} />,
};

export const TopRightViewport: Story = {
  args: {
    viewportClassName: "bottom-auto top-0",
  },
  render: (args) => <ToastDemo {...args} />,
};

export const ShortDuration: Story = {
  args: {
    duration: 1500,
  },
  render: (args) => <ToastDemo {...args} />,
};

/** Every variant at once, kept on screen (duration Infinity) for review. */
function VariantsDemo(props: ToasterProps): React.ReactElement {
  const { toast } = useToast();
  React.useEffect(() => {
    // Stable ids: a re-run (StrictMode) replaces instead of stacking.
    toast({ id: "story-default", title: "Event deleted", duration: Infinity });
    toast({
      id: "story-success",
      variant: "success",
      title: "Event saved",
      description: "Your changes are live.",
      duration: Infinity,
    });
    toast({
      id: "story-info",
      variant: "info",
      title: "Sync scheduled",
      description: "Venues refresh every hour.",
      duration: Infinity,
    });
    toast({
      id: "story-error",
      variant: "error",
      title: "Save failed",
      description: "The server rejected the request.",
      duration: Infinity,
      action: (
        <Button size="sm" variant="outline" className="text-foreground">
          Retry
        </Button>
      ),
    });
  }, [toast]);
  return <Toaster {...props} />;
}

/**
 * Errors are announced at once (assertive), the rest politely. F8 moves
 * focus to the toasts, Tab walks them, Escape dismisses the focused one;
 * hovering or focusing pauses the timers.
 */
export const Variants: Story = {
  render: (args) => <VariantsDemo {...args} />,
};
