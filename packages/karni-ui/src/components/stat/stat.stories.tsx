import type { Meta, StoryObj } from "@storybook/react";
import { Stat } from "./stat";

function UsersIcon(): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable={false}
    >
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

const meta = {
  title: "Support/Stat",
  component: Stat,
  tags: ["autodocs"],
  args: {
    label: "Active users",
    value: "1,284",
  },
} satisfies Meta<typeof Stat>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {
  args: {
    delta: 132,
    icon: <UsersIcon />,
  },
};

export const NegativeDelta: Story = {
  args: {
    label: "Signups",
    value: "87",
    delta: -14,
  },
};

export const CustomDeltaFormat: Story = {
  args: {
    label: "Conversion",
    value: "4.2%",
    delta: 0.4,
    formatDelta: (delta) => `${delta >= 0 ? "+" : ""}${String(delta)} pts`,
  },
};

export const KpiRow: Story = {
  render: () => (
    <div className="grid w-full max-w-3xl gap-4 sm:grid-cols-3">
      <Stat label="Revenue" value="$48.2k" delta={2400} icon={<UsersIcon />} />
      <Stat label="Events" value="312" delta={-8} />
      <Stat label="Uptime" value="99.9%" delta={<span>steady</span>} />
    </div>
  ),
};

export const Loading: Story = {
  args: { loading: true, icon: <UsersIcon />, className: "max-w-64" },
};

/** Up, down and flat: an arrow (or dash) and spoken context, not colour alone. */
export const Trends: Story = {
  render: () => (
    <div className="grid w-full max-w-3xl gap-4 sm:grid-cols-3">
      <Stat label="Signups" value="1,284" delta={132} />
      <Stat label="Bookings" value="312" delta={-18} />
      <Stat label="Venues" value="24" delta={0} />
    </div>
  ),
};
