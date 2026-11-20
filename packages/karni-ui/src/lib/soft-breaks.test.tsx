import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RowCard } from "../components/resource/table/RowCard";
import { softBreaks } from "./soft-breaks";

describe("softBreaks", () => {
  it("lets an email wrap after the @ and before its dots, never inside a word", () => {
    const { container } = render(<p>{softBreaks("lena.vogt@example.com")}</p>);
    expect(container.textContent).toBe("lena.vogt@example.com");
    const html = container.innerHTML;
    expect(html).toBe("<p>lena<wbr>.vogt@<wbr>example<wbr>.com</p>");
  });

  it("leaves short words alone and reaches text inside an element", () => {
    expect(softBreaks("Paid")).toBe("Paid");
    const { container } = render(
      <div>{softBreaks(<a href="mailto:x">jon.mbeki@example.com</a>)}</div>,
    );
    expect(container.querySelector("a")?.querySelectorAll("wbr").length).toBe(3);
  });
});

describe("RowCard values", () => {
  it("give a long email room and wrap points", () => {
    const { container } = render(
      <ul>
        <RowCard
          row={{}}
          title="1004"
          fields={[{ id: "email", label: "Email", value: "lena.vogt@example.com" }]}
          selected={false}
          density="comfortable"
        />
      </ul>,
    );
    const list = container.querySelector("dl");
    expect(list?.className).toContain("grid-cols-[fit-content(40%)_minmax(0,1fr)]");
    expect(container.querySelector("dd")?.querySelectorAll("wbr").length).toBe(3);
    expect(container.querySelector("dd")?.textContent).toBe("lena.vogt@example.com");
  });
});
