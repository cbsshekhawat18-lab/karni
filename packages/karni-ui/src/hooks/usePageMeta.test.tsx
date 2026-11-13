import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { usePageMeta, type PageMeta } from "./usePageMeta";

function Meta(props: PageMeta) {
  usePageMeta(props);
  return null;
}

describe("usePageMeta", () => {
  it("sets the title and the description, and puts back the old ones", () => {
    document.title = "Before";
    const { rerender, unmount } = render(
      <Meta title="Brass Lamp" siteName="Corner Shop" description="A warm desk lamp." />,
    );
    expect(document.title).toBe("Brass Lamp | Corner Shop");
    const tag = document.head.querySelector('meta[name="description"]');
    expect(tag?.getAttribute("content")).toBe("A warm desk lamp.");
    rerender(<Meta title="Corner Shop" siteName="Corner Shop" />);
    expect(document.title).toBe("Corner Shop");
    unmount();
    expect(document.title).toBe("Before");
  });
});
