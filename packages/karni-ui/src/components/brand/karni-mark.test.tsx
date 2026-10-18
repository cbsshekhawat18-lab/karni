import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Layout } from "../layout/layout";
import { KarniMark } from "./karni-mark";
import { MARK_PATHS } from "./mark-paths";

describe("Layout's logo slot", () => {
  it("shows the Karni mark by default and yields to a project's own brand", () => {
    const { unmount } = render(<Layout navItems={[]}>x</Layout>);
    expect(screen.getAllByRole("img", { name: "Karni" }).length).toBeGreaterThan(0);
    unmount();
    render(
      <Layout navItems={[]} sidebarHeader={<span>Acme</span>}>
        x
      </Layout>,
    );
    expect(screen.queryByRole("img", { name: "Karni" })).toBeNull();
    expect(screen.getAllByText("Acme").length).toBeGreaterThan(0);
  });
});

describe("KarniMark", () => {
  it("renders the full mark above 32px with the three brand fills", () => {
    const { container } = render(<KarniMark size={48} />);
    const svg = screen.getByRole("img", { name: "Karni" });
    expect(svg.getAttribute("width")).toBe("48");
    const fills = [...container.querySelectorAll("path")].map((p) => p.getAttribute("fill"));
    expect(fills).toEqual(MARK_PATHS.map((p) => p.fill));
    expect(fills).toEqual(["#000000", "#FB5D08", "#FFFFFF"]);
  });

  it("switches to the small-size variant at 32px and below", () => {
    const { container } = render(<KarniMark size={24} />);
    expect(container.querySelectorAll("circle")).toHaveLength(3);
    expect(container.querySelector("path[stroke]")).not.toBeNull();
  });

  it("can be forced to either variant and hidden from assistive tech", () => {
    const { container } = render(<KarniMark size={16} variant="full" title="" />);
    expect(container.querySelectorAll("path")).toHaveLength(MARK_PATHS.length);
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    expect(screen.queryByRole("img")).toBeNull();
  });
});
