import type { Meta, StoryObj } from "@storybook/react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs";

const meta = {
  title: "Primitives/Tabs",
  component: Tabs,
  tags: ["autodocs"],
} satisfies Meta<typeof Tabs>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {
  render: () => (
    <Tabs defaultValue="details" className="w-96">
      <TabsList>
        <TabsTrigger value="details">Details</TabsTrigger>
        <TabsTrigger value="attendees">Attendees</TabsTrigger>
        <TabsTrigger value="settings" disabled>
          Settings
        </TabsTrigger>
      </TabsList>
      <TabsContent value="details">
        <p className="text-sm text-muted-foreground">Everything about the record.</p>
      </TabsContent>
      <TabsContent value="attendees">
        <p className="text-sm text-muted-foreground">Who is coming.</p>
      </TabsContent>
      <TabsContent value="settings">
        <p className="text-sm text-muted-foreground">Unreachable while disabled.</p>
      </TabsContent>
    </Tabs>
  ),
};
