import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import * as React from "react";
import { screen, userEvent, waitFor } from "storybook/test";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { Label } from "../../primitives/label";
import { ResourceSelect, type ResourceSelectProps } from "./ResourceSelect";
import { venueBackend, type VenueBackendOptions } from "./venue-backend";

/**
 * One story per state, against msw handlers that simulate a Karni `venues`
 * resource (any size, with or without search, failing on demand). Open
 * states get there through a play function.
 */
function Providers(props: { children: React.ReactNode }): React.ReactElement {
  const [context] = React.useState(() => ({
    client: createKarniClient({ baseUrl: `${window.location.origin}/api` }),
    queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  }));
  return (
    <KarniProvider client={context.client} queryClient={context.queryClient}>
      {props.children}
    </KarniProvider>
  );
}

function backend(options: VenueBackendOptions = {}): { msw: { handlers: unknown[] } } {
  return { msw: { handlers: venueBackend(options).handlers } };
}

type PickerArgs = Omit<ResourceSelectProps, "onChange"> & {
  label?: string;
  error?: string;
  help?: string;
};

/** A labelled field around the picker, holding its value like a form would. */
function Field(args: PickerArgs): React.ReactElement {
  const { label = "Venue", error, help, value: initial, ...rest } = args;
  const [value, setValue] = React.useState(initial);
  const helpId = help !== undefined ? "venue-help" : undefined;
  const errorId = error !== undefined ? "venue-error" : undefined;
  const describedBy = [helpId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="max-w-sm [&>:not([hidden])~:not([hidden])]:mt-2">
      <Label htmlFor="venue">{label}</Label>
      <ResourceSelect
        id="venue"
        {...rest}
        value={value}
        onChange={setValue}
        aria-describedby={describedBy}
        aria-invalid={error !== undefined || undefined}
      />
      {help !== undefined ? (
        <p id={helpId} className="text-sm text-muted-foreground">
          {help}
        </p>
      ) : null}
      {error !== undefined ? (
        <p id={errorId} className="text-sm font-medium text-foreground">
          {error}
        </p>
      ) : null}
    </div>
  );
}

const meta = {
  title: "Resource/ResourceSelect",
  component: Field,
  args: { resource: "venues", value: null, placeholder: "Choose a venue" },
  parameters: {
    ...backend(),
    a11y: {
      disableRules: {
        "scrollable-region-focusable":
          "The options are reached from the search input (aria-activedescendant: arrows, Home/End, PageUp/PageDown), which scrolls the active one into view. A tab stop on the list would be a second, dead focus target.",
      },
    },
  },
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
} satisfies Meta<typeof Field>;

export default meta;
type Story = StoryObj<typeof meta>;

async function open(): Promise<void> {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("combobox"));
}

async function openAndType(text: string): Promise<void> {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("combobox"));
  await screen.findByRole("listbox");
  await user.keyboard(text);
}

export const Closed: Story = { args: { help: "Where the event takes place." } };

export const Open: Story = {
  play: async () => {
    await open();
    const user = userEvent.setup();
    await screen.findByRole("option", { name: "Aurora Hall" });
    await user.keyboard("{ArrowDown}{ArrowDown}");
  },
};

/** A preselected id is labelled from the API, never shown as a bare id. */
export const Preselected: Story = { args: { value: 7 } };

export const Multiple: Story = {
  args: { value: [1, 7, 11], multiple: true, label: "Venues" },
};

/** The first page is loading: placeholder rows, announced. */
export const LoadingOptions: Story = {
  parameters: backend({ listDelay: "infinite" }),
  play: open,
};

/** A new search is loading: the previous rows stay, dimmed, and the list says so. */
export const Searching: Story = {
  parameters: backend({ searchDelay: "infinite" }),
  play: () => openAndType("har"),
};

export const NoMatch: Story = {
  play: () => openAndType("zzz"),
};

/** Nothing exists yet: said differently from "nothing matches". */
export const NoneYet: Story = {
  parameters: backend({ count: 0 }),
  play: open,
};

/** 10,000 venues: one page at a time, more as the list scrolls, and how many there are. */
export const TenThousand: Story = {
  parameters: backend({ count: 10_000 }),
  play: async () => {
    await open();
    await screen.findByRole("option", { name: "Aurora Hall" });
  },
};

/** The API cannot search venues (no search_fields): typing narrows what is loaded, and the list says so. */
export const SearchUnavailable: Story = {
  parameters: backend({ count: 10_000, search: false }),
  play: () => openAndType("venue 0004"),
};

export const ServerError: Story = {
  parameters: backend({ listFailure: 500 }),
  play: open,
};

export const Forbidden: Story = {
  parameters: backend({ listFailure: 403 }),
  play: open,
};

export const Offline: Story = {
  parameters: backend({ listFailure: "offline" }),
  play: open,
};

/** A value whose row cannot be loaded (deleted, or hidden from this role) says so. */
export const UnloadableValue: Story = {
  args: { value: [7, 9999], multiple: true, label: "Venues" },
  play: async () => {
    await waitFor(() => screen.getByText("Couldn't load venue 9999"), { timeout: 3000 });
  },
};

export const Invalid: Story = {
  args: { error: "Choose a venue for the event." },
};

export const Disabled: Story = { args: { value: 7, disabled: true } };
