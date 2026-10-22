import type { Meta, StoryObj } from "@storybook/react";
import * as React from "react";
import { Label } from "../primitives/label";
import { FileUpload } from "./FileUpload";
import type { FileUploadProps } from "./FileUpload";

const meta = {
  title: "Resource/FileUpload",
  component: FileUpload,
  tags: ["autodocs"],
  args: {
    multiple: false,
    disabled: false,
    clearable: true,
  },
} satisfies Meta<typeof FileUpload>;

export default meta;
type Story = StoryObj<typeof meta>;

function ControlledFileUpload(props: FileUploadProps): React.ReactElement {
  const [value, setValue] = React.useState<FileUploadProps["value"]>(props.value ?? null);
  return <FileUpload {...props} value={value} onChange={setValue} />;
}

export const Playground: Story = {
  render: (args) => <ControlledFileUpload {...args} />,
};

export const ExistingUpload: Story = {
  render: (args) => (
    <ControlledFileUpload {...args} value="https://files.example.com/events/launch.png" />
  ),
};

export const MultipleImages: Story = {
  render: (args) => <ControlledFileUpload {...args} multiple accept="image/*" />,
};

export const WithSizeLimit: Story = {
  render: (args) => (
    <ControlledFileUpload
      {...args}
      maxSize={1024 * 1024}
      onReject={(file, reason) => {
        console.warn(`[story] rejected ${file.name}: ${reason}`);
      }}
    />
  ),
};

export const CustomContent: Story = {
  render: (args) => (
    <ControlledFileUpload {...args} accept="image/*">
      <span className="text-sm font-medium">Drop your avatar here</span>
    </ControlledFileUpload>
  ),
};

export const Disabled: Story = {
  args: { disabled: true, value: "https://files.example.com/events/launch.png" },
};

/** A <label htmlFor> names the dropzone, as a form field's label does. */
export const WithLabel: Story = {
  render: (args) => (
    <div className="grid max-w-md gap-1.5">
      <Label htmlFor="story-cover">Cover image</Label>
      <ControlledFileUpload {...args} id="story-cover" accept="image/*" />
    </div>
  ),
};

/** The `error` prop: shown under the dropzone, announced, and the dropzone is invalid. */
export const WithError: Story = {
  render: (args) => (
    <div className="grid max-w-md gap-1.5">
      <Label htmlFor="story-error">Cover image</Label>
      <ControlledFileUpload
        {...args}
        id="story-error"
        accept="image/*"
        error="Choose an image for the event's cover."
      />
    </div>
  ),
};

/** Invalid from a form: aria-invalid plus the form's own message through aria-describedby. */
export const Invalid: Story = {
  render: (args) => (
    <div className="grid max-w-md gap-1.5">
      <Label htmlFor="story-invalid">Attachment</Label>
      <ControlledFileUpload
        {...args}
        id="story-invalid"
        aria-invalid
        aria-describedby="story-invalid-error"
      />
      <p id="story-invalid-error" className="text-sm text-destructive">
        This field is required.
      </p>
    </div>
  ),
};

const poster = new File([new Uint8Array(48_000)], "launch-poster.png", { type: "image/png" });

export const Uploading: Story = {
  render: (args) => <FileUpload {...args} uploading value={poster} />,
};
