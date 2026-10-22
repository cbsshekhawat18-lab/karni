/**
 * Layout's focus after a client-side navigation (`routeFocus`): the new
 * page's <h1> takes focus and a live region says its title, except on the
 * first load, on a search-param change, or when the page placed focus itself.
 *
 * A small router stands in for a real one: `navigate` pushes the URL and
 * renders the page, through the NavLink slot as an app would plug one in.
 */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Page } from "../page/page";
import { Layout, type LayoutNavLinkProps, type LayoutProps } from "./layout";

const NavigateContext = React.createContext<(to: string) => void>(() => undefined);

function RouterLink(props: LayoutNavLinkProps): React.ReactElement {
  const navigate = React.useContext(NavigateContext);
  return (
    <a
      href={props.href}
      className={props.className}
      aria-current={props["aria-current"]}
      onClick={(event) => {
        event.preventDefault();
        props.onClick();
        navigate(props.href);
      }}
    >
      {props.children}
    </a>
  );
}

function TitledPage(): React.ReactElement {
  React.useEffect(() => {
    document.title = "Reports · Acme";
  }, []);
  return <Page title="Reports">Monthly numbers.</Page>;
}

/** The page for a URL. `/events` pages through `?page=` without leaving the route. */
function Screen({ url }: { url: string }): React.ReactElement {
  const navigate = React.useContext(NavigateContext);
  const [pathname, search = ""] = url.split("?");
  if (pathname === "/venues" || pathname === "/#/venues") {
    return <Page title="Venues">Four venues.</Page>;
  }
  if (pathname === "/reports") return <TitledPage />;
  if (pathname === "/events/new") {
    return (
      <Page title="New event">
        <input aria-label="Event title" autoFocus />
      </Page>
    );
  }
  const page = Number(new URLSearchParams(search).get("page") ?? "1");
  return (
    <Page title="Events">
      <p>Page {page}</p>
      <button type="button" onClick={() => navigate(`/events?page=${page + 1}`)}>
        Next page
      </button>
    </Page>
  );
}

const PATHS = ["/events", "/venues", "/reports", "/events/new"];

interface AppProps {
  start?: string;
  routeFocus?: LayoutProps["routeFocus"];
  /** The route changes now, its page only on `controls.commit()` (a router waiting for data). */
  controls?: { commit?: () => void };
  /** Keep the URL as it is (a memory router). The route lives in state only. */
  memory?: boolean;
  /** Route links as `#/path` (a hash router). */
  hash?: boolean;
}

function App({
  start = "/events",
  routeFocus,
  controls,
  memory = false,
  hash = false,
}: AppProps): React.ReactElement {
  const [url, setUrl] = React.useState(start);
  const [shown, setShown] = React.useState(start);
  const navigate = React.useCallback(
    (to: string) => {
      if (!memory) window.history.pushState(null, "", to);
      setUrl(to);
      if (controls === undefined) setShown(to);
    },
    [controls, memory],
  );
  if (controls !== undefined) controls.commit = () => setShown(url);
  const items = PATHS.map((path) => {
    const href = hash ? `/#${path}` : path;
    return { href, label: path.slice(1), active: url.split("?")[0] === href };
  });
  return (
    <NavigateContext.Provider value={navigate}>
      <Layout navItems={items} slots={{ NavLink: RouterLink }} routeFocus={routeFocus}>
        <Screen url={shown} />
      </Layout>
    </NavigateContext.Provider>
  );
}

function live(): HTMLElement {
  return screen.getByRole("status");
}

/** Lets the Layout's deferred work run, for asserting that nothing moved. */
async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

async function follow(user: ReturnType<typeof userEvent.setup>, name: string): Promise<void> {
  const nav = screen.getByRole("navigation", { name: "Main" });
  within(nav).getByRole("link", { name }).focus();
  await user.keyboard("{Enter}");
}

beforeEach(() => {
  window.history.replaceState(null, "", "/events");
});

afterEach(() => {
  window.history.replaceState(null, "", "/");
  document.title = "";
});

describe("Layout focus after a navigation", () => {
  it("moves focus to the new page's heading and says its title", async () => {
    window.history.replaceState(null, "", "/venues");
    const user = userEvent.setup();
    render(<App start="/venues" />);
    await follow(user, "events");
    const heading = screen.getByRole("heading", { level: 1, name: "Events" });
    await waitFor(() => expect(heading).toHaveFocus());
    // Focusable by script only, so it never becomes a Tab stop.
    expect(heading).toHaveAttribute("tabindex", "-1");
    expect(live()).toHaveTextContent("Events");
    // The next Tab continues in the new page, not from the top of the document.
    await user.tab();
    expect(screen.getByRole("button", { name: "Next page" })).toHaveFocus();
  });

  it("says the document title when the new page sets one", async () => {
    const user = userEvent.setup();
    render(<App />);
    await follow(user, "reports");
    await waitFor(() => expect(screen.getByRole("heading", { name: "Reports" })).toHaveFocus());
    expect(live()).toHaveTextContent("Reports · Acme");
  });

  it("leaves focus alone on the first load", async () => {
    render(<App />);
    await settle();
    expect(document.body).toHaveFocus();
    expect(live()).toBeEmptyDOMElement();
  });

  it("leaves focus alone after a redirect during the first load, and works from the first action on", async () => {
    window.history.replaceState(null, "", "/");
    function Redirecting(): React.ReactElement {
      const [url, setUrl] = React.useState("/");
      React.useEffect(() => {
        // What a router's redirect does before anyone touches the page.
        window.history.replaceState(null, "", "/venues");
        setUrl("/venues");
      }, []);
      return (
        <NavigateContext.Provider
          value={(to) => {
            window.history.pushState(null, "", to);
            setUrl(to);
          }}
        >
          <Layout navItems={[{ href: "/events", label: "events" }]} slots={{ NavLink: RouterLink }}>
            {url === "/" ? <p>Loading</p> : <Screen url={url} />}
          </Layout>
        </NavigateContext.Provider>
      );
    }
    const user = userEvent.setup();
    render(<Redirecting />);
    expect(await screen.findByRole("heading", { name: "Venues" })).toBeInTheDocument();
    await settle();
    expect(document.body).toHaveFocus();
    expect(live()).toBeEmptyDOMElement();
    await follow(user, "events");
    await waitFor(() => expect(screen.getByRole("heading", { name: "Events" })).toHaveFocus());
  });

  it("keeps focus where it is when only search params change (pagination, filters)", async () => {
    const user = userEvent.setup();
    render(<App />);
    const next = screen.getByRole("button", { name: "Next page" });
    next.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByText("Page 2")).toBeInTheDocument();
    expect(window.location.search).toBe("?page=2");
    await settle();
    expect(next).toHaveFocus();
    expect(live()).toBeEmptyDOMElement();
  });

  it("leaves focus on a field the new page focused itself, and still says the title", async () => {
    const user = userEvent.setup();
    render(<App />);
    await follow(user, "events/new");
    const field = await screen.findByRole("textbox", { name: "Event title" });
    await waitFor(() => expect(live()).toHaveTextContent("New event"));
    expect(field).toHaveFocus();
  });

  it("waits for the new page when the route changes before its content does", async () => {
    const user = userEvent.setup();
    const controls: AppProps["controls"] = {};
    render(<App controls={controls} />);
    await follow(user, "venues");
    expect(window.location.pathname).toBe("/venues");
    await settle();
    // The old page is still up: its heading is not the one to focus.
    expect(screen.getByRole("heading", { name: "Events" })).not.toHaveFocus();
    act(() => controls.commit?.());
    await waitFor(() => expect(screen.getByRole("heading", { name: "Venues" })).toHaveFocus());
    expect(live()).toHaveTextContent("Venues");
  });

  it("follows a hash router's route (#/venues)", async () => {
    window.history.replaceState(null, "", "/#/events");
    const user = userEvent.setup();
    render(<App start="/#/events" hash />);
    await follow(user, "venues");
    await waitFor(() => expect(screen.getByRole("heading", { name: "Venues" })).toHaveFocus());
  });

  it("hands focus to the new page after a link in the mobile drawer, not back to the menu button", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    const drawer = screen.getByRole("dialog", { name: "Navigation" });
    await user.click(within(drawer).getByRole("link", { name: "venues" }));
    const heading = screen.getByRole("heading", { name: "Venues" });
    await waitFor(() => expect(heading).toHaveFocus());
    await settle();
    expect(heading).toHaveFocus();
  });
});

describe("Layout routeFocus escape hatches", () => {
  it("routeFocus={false} leaves focus where it was and renders no live region", async () => {
    const user = userEvent.setup();
    render(<App routeFocus={false} />);
    await follow(user, "venues");
    expect(screen.getByRole("heading", { name: "Venues" })).toBeInTheDocument();
    await settle();
    expect(screen.getByRole("link", { name: "venues" })).toHaveFocus();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("routeKey drives it when the URL does not change (a memory router)", async () => {
    function MemoryApp(): React.ReactElement {
      const [path, setPath] = React.useState("/events");
      return (
        <NavigateContext.Provider value={setPath}>
          <Layout
            navItems={[{ href: "/venues", label: "venues" }]}
            slots={{ NavLink: RouterLink }}
            routeFocus={{ routeKey: path }}
          >
            <Screen url={path} />
          </Layout>
        </NavigateContext.Provider>
      );
    }
    const user = userEvent.setup();
    render(<MemoryApp />);
    await follow(user, "venues");
    expect(window.location.pathname).toBe("/events");
    await waitFor(() => expect(screen.getByRole("heading", { name: "Venues" })).toHaveFocus());
  });

  it("getTarget and getAnnouncement choose what takes focus and what is said", async () => {
    const user = userEvent.setup();
    render(
      <App
        routeFocus={{
          getTarget: (main) => main.querySelector("section"),
          getAnnouncement: (target) => `Now on ${target.querySelector("h1")?.textContent ?? ""}`,
        }}
      />,
    );
    await follow(user, "venues");
    await waitFor(() => expect(live()).toHaveTextContent("Now on Venues"));
    expect(screen.getByRole("main").querySelector("section")).toHaveFocus();
  });
});
