import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { MarkdownView, preloadMarkdown } from "./markdown-view";
import { renderMarkdown, type MarkdownRenderOptions } from "./render";
import { axeViolations } from "../../../tests/axe";

const OPTIONS: MarkdownRenderOptions = {
  allowHtml: false,
  headingOffset: 1,
  externalLinks: "new-tab",
  isLinkAllowed: undefined,
  addTags: [],
  addAttributes: [],
  origin: "http://localhost:3000",
};

function html(source: string, options: Partial<MarkdownRenderOptions> = {}): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderMarkdown(source, { ...OPTIONS, ...options });
  return host;
}

describe("MarkdownView", () => {
  it("shows a placeholder until the renderer loads, then the formatted text", async () => {
    render(<MarkdownView source={"# Notes\n\nThe **garden** range."} data-testid="md" />);
    expect(await screen.findByRole("heading", { level: 2, name: "Notes" })).toBeInTheDocument();
    expect(screen.getByText("garden").tagName).toBe("STRONG");
    expect(screen.getByTestId("md")).not.toHaveAttribute("aria-busy");
  });

  describe("once loaded", () => {
    beforeAll(async () => {
      await preloadMarkdown();
    });

    it("renders synchronously, with headings one level down unless told otherwise", () => {
      const { rerender } = render(<MarkdownView source={"# Title\n## Sub"} />);
      expect(screen.getByRole("heading", { level: 2, name: "Title" })).toBeInTheDocument();
      expect(screen.getByRole("heading", { level: 3, name: "Sub" })).toBeInTheDocument();
      rerender(<MarkdownView source={"# Title"} headingOffset={0} />);
      expect(screen.getByRole("heading", { level: 1, name: "Title" })).toBeInTheDocument();
    });

    it("renders nothing for no source", () => {
      const { container } = render(<MarkdownView source={null} />);
      expect(container).toBeEmptyDOMElement();
    });

    it("passes axe with lists, a table, a quote and code", async () => {
      const { container } = render(
        <MarkdownView
          source={
            "Intro with a [link](/catalog).\n\n- one\n- two\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n> quote\n\n`code`"
          }
        />,
      );
      expect(await axeViolations(container)).toEqual([]);
    });
  });
});

describe("renderMarkdown sanitizing", () => {
  it("shows raw HTML as text by default: a script is never an element", () => {
    const out = html('Hello <script>alert("x")</script> <b onclick="steal()">bold</b>');
    expect(out.querySelector("script")).toBeNull();
    expect(out.querySelector("b")).toBeNull();
    expect(out.textContent).toContain('<script>alert("x")</script>');
    expect(out.innerHTML).not.toMatch(/<script/i);
  });

  it("with allowHtml keeps safe HTML and drops scripts and event handlers", () => {
    const out = html(
      [
        "<em>kept</em>",
        "<script>alert(1)</script>",
        '<img src="x.png" alt="pic" onerror="alert(2)">',
        '<a href="/ok" onmouseover="alert(3)">hover</a>',
        '<div style="position:fixed" onclick="alert(4)">styled</div>',
        '<iframe src="https://example.com"></iframe>',
        '<form action="/steal"><input name="pw"></form>',
        '<svg onload="alert(5)"><circle /></svg>',
      ].join("\n\n"),
      { allowHtml: true },
    );
    expect(out.querySelector("em")?.textContent).toBe("kept");
    expect(out.querySelector("script, iframe, form, input, svg")).toBeNull();
    const img = out.querySelector("img");
    expect(img?.getAttribute("alt")).toBe("pic");
    for (const element of Array.from(out.querySelectorAll("*"))) {
      for (const attribute of Array.from(element.attributes)) {
        expect(attribute.name).not.toMatch(/^on/i);
        expect(attribute.name).not.toBe("style");
      }
    }
  });

  it("drops javascript:, data: and other unsafe link targets but keeps the text", () => {
    const out = html(
      [
        "[a](javascript:alert(1))",
        "[b](JaVaScRiPt:alert(1))",
        "[c](data:text/html;base64,PHNjcmlwdD4=)",
        "[d](vbscript:msgbox(1))",
        '<a href="java&#x09;script:alert(1)">e</a>',
      ].join(" "),
      { allowHtml: true },
    );
    const links = Array.from(out.querySelectorAll("a"));
    expect(links.map((link) => link.textContent)).toEqual(["a", "b", "c", "d", "e"]);
    for (const link of links) expect(link.hasAttribute("href")).toBe(false);
  });

  it("keeps safe links; one to another site gets noopener and opens in a new tab", () => {
    const out = html(
      "[home](/catalog) [mail](mailto:team@example.com) [site](https://example.org/x)",
    );
    const [home, mail, site] = Array.from(out.querySelectorAll("a"));
    expect(home?.getAttribute("href")).toBe("/catalog");
    expect(home?.hasAttribute("target")).toBe(false);
    expect(mail?.getAttribute("href")).toBe("mailto:team@example.com");
    expect(site?.getAttribute("rel")).toBe("noopener noreferrer nofollow");
    expect(site?.getAttribute("target")).toBe("_blank");
    const same = html("[site](https://example.org/x)", { externalLinks: "same-tab" });
    expect(same.querySelector("a")?.hasAttribute("target")).toBe(false);
  });

  it("lets a project drop links (isLinkAllowed) and allow more tags (addTags)", () => {
    const out = html("[in](/a) [out](https://other.example/b)", {
      isLinkAllowed: (href) => href.startsWith("/"),
    });
    const [inside, outside] = Array.from(out.querySelectorAll("a"));
    expect(inside?.getAttribute("href")).toBe("/a");
    expect(outside?.hasAttribute("href")).toBe(false);
    expect(html("<x-chip>hit</x-chip>", { allowHtml: true }).querySelector("x-chip")).toBeNull();
    const added = html("<x-chip>hit</x-chip>", { allowHtml: true, addTags: ["x-chip"] });
    expect(added.querySelector("x-chip")?.textContent).toBe("hit");
  });

  it("renders GitHub-flavoured tables and strikethrough", () => {
    const out = html("| A | B |\n|---|---|\n| 1 | 2 |\n\n~~gone~~");
    expect(out.querySelectorAll("table th")).toHaveLength(2);
    expect(out.querySelector("del")?.textContent).toBe("gone");
  });
});
