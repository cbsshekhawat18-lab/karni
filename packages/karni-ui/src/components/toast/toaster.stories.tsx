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
