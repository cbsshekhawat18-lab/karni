import type { Meta, StoryObj } from "@storybook/react";
import * as React from "react";
import { Button } from "../primitives/button";
import { Input } from "../primitives/input";
import { Label } from "../primitives/label";
import { Modal, ModalClose } from "./modal";

const meta = {
  title: "Support/Modal",
  component: Modal,
  tags: ["autodocs"],
  args: {
    title: "Edit event",
    description: "Make changes and save when you are done.",
  },
} satisfies Meta<typeof Modal>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {
  args: {
    trigger: <Button>Open modal</Button>,
    children: (
      <p className="text-sm text-muted-foreground">
        Any content renders here: forms, text, a ResourceForm.
      </p>
    ),
  },
};

export const WithFooterActions: Story = {
  args: {
    title: "Delete event",
    description: "This cannot be undone.",
    trigger: <Button variant="destructive">Delete</Button>,
    footer: (
      <>
        <ModalClose asChild>
          <Button variant="outline">Cancel</Button>
        </ModalClose>
        <Button variant="destructive">Delete event</Button>
      </>
    ),
  },
};

/**
 * Open on load: named by its title, described by its description. Focus
 * starts on the first field, Tab stays inside, Escape closes.
 */
export const Open: Story = {
  args: {
    defaultOpen: true,
    trigger: <Button>Open modal</Button>,
    children: (
      <div className="grid gap-1.5">
        <Label htmlFor="story-modal-title">Title</Label>
        <Input id="story-modal-title" defaultValue="Launch party" />
      </div>
    ),
    footer: (
      <>
        <ModalClose asChild>
          <Button variant="outline">Cancel</Button>
        </ModalClose>
        <Button>Save changes</Button>
      </>
    ),
  },
};

export const OpenDestructive: Story = {
  args: {
    defaultOpen: true,
    title: "Delete event",
    description: "This cannot be undone. Bookings for the event are cancelled.",
    trigger: <Button variant="destructive">Delete</Button>,
    footer: (
      <>
        <ModalClose asChild>
          <Button variant="outline">Cancel</Button>
        </ModalClose>
        <Button variant="destructive">Delete event</Button>
      </>
    ),
  },
};

function ControlledDemo(): React.ReactElement {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="flex items-center gap-3">
      <Button
        onClick={() => {
          setOpen(true);
        }}
      >
        Open (controlled)
      </Button>
      <Modal
        title="Controlled modal"
        description="State lives in the parent component."
        open={open}
        onOpenChange={setOpen}
        footer={
          <Button
            variant="outline"
            onClick={() => {
              setOpen(false);
            }}
          >
            Done
          </Button>
        }
      >
        <p className="text-sm text-muted-foreground">Pair `open` with `onOpenChange`.</p>
      </Modal>
    </div>
  );
}

export const Controlled: Story = {
  args: { title: "Controlled modal" },
  render: () => <ControlledDemo />,
};
