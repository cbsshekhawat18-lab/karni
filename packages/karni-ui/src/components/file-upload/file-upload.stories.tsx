import type { Meta, StoryObj } from "@storybook/react";
import * as React from "react";
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
