import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FileUpload } from "./FileUpload";

function fileInputOf(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector('input[type="file"]');
  if (!(input instanceof HTMLInputElement)) throw new Error("file input not rendered");
  return input;
}

describe("FileUpload", () => {
  it("emits the picked File through the hidden input", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { container } = render(<FileUpload onChange={onChange} />);

    const file = new File(["hello"], "hello.png", { type: "image/png" });
    await user.upload(fileInputOf(container), file);

    expect(onChange).toHaveBeenCalledWith(file);
  });

  it("emits File[] in multiple mode", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { container } = render(<FileUpload multiple onChange={onChange} />);

    const first = new File(["a"], "a.png", { type: "image/png" });
    const second = new File(["b"], "b.png", { type: "image/png" });
    await user.upload(fileInputOf(container), [first, second]);

    expect(onChange).toHaveBeenCalledWith([first, second]);
  });

  it("accepts files dropped onto the dropzone and tracks the dragging state", () => {
    const onChange = vi.fn();
    render(<FileUpload onChange={onChange} />);
    const dropzone = screen.getByRole("button", { name: /click to browse/ });

    fireEvent.dragOver(dropzone, { dataTransfer: { files: [] } });
    expect(dropzone).toHaveAttribute("data-dragging", "true");

    const file = new File(["drop"], "drop.pdf", { type: "application/pdf" });
    fireEvent.drop(dropzone, { dataTransfer: { files: [file] } });

    expect(dropzone).not.toHaveAttribute("data-dragging");
    expect(onChange).toHaveBeenCalledWith(file);
  });

  it("rejects dropped files that do not match accept", () => {
    const onChange = vi.fn();
    const onReject = vi.fn();
    render(<FileUpload accept=".png,image/jpeg" onChange={onChange} onReject={onReject} />);

    const bad = new File(["nope"], "notes.txt", { type: "text/plain" });
    fireEvent.drop(screen.getByRole("button", { name: /click to browse/ }), {
      dataTransfer: { files: [bad] },
    });

    expect(onReject).toHaveBeenCalledWith(bad, "accept");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("rejects files over maxSize", () => {
    const onChange = vi.fn();
    const onReject = vi.fn();
    render(<FileUpload maxSize={3} onChange={onChange} onReject={onReject} />);

    const big = new File(["12345"], "big.png", { type: "image/png" });
    fireEvent.drop(screen.getByRole("button", { name: /click to browse/ }), {
      dataTransfer: { files: [big] },
    });

    expect(onReject).toHaveBeenCalledWith(big, "size");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows an existing URL value as a link named by its basename", () => {
    render(<FileUpload value="https://files.example.com/events/launch.png?sig=abc" />);
    const link = screen.getByRole("link", { name: "launch.png" });
    expect(link).toHaveAttribute("href", "https://files.example.com/events/launch.png?sig=abc");
  });

  it("shows a pending File with its name and size", () => {
    const file = new File(["hello"], "hello.png", { type: "image/png" });
    render(<FileUpload value={file} />);
    expect(screen.getByText(/hello\.png/)).toBeInTheDocument();
    expect(screen.getByText("5 B")).toBeInTheDocument();
  });

  it("clearing the single value emits null", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<FileUpload value="https://files.example.com/launch.png" onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "Remove launch.png" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("removing one of several files emits the remaining File values", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const keep = new File(["keep"], "keep.png", { type: "image/png" });
    const drop = new File(["drop"], "drop.png", { type: "image/png" });
    render(<FileUpload multiple value={[keep, drop]} onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "Remove drop.png" }));
    expect(onChange).toHaveBeenCalledWith([keep]);
  });

  it("hides the remove affordance when clearable is false", () => {
    render(<FileUpload value="https://files.example.com/launch.png" clearable={false} />);
    expect(screen.queryByRole("button", { name: "Remove launch.png" })).not.toBeInTheDocument();
  });

  it("does nothing while disabled", () => {
    const onChange = vi.fn();
    render(<FileUpload disabled onChange={onChange} value="https://files.example.com/x.png" />);

    const dropzone = screen.getByRole("button", { name: /click to browse/ });
    expect(dropzone).toBeDisabled();

    const file = new File(["drop"], "drop.png", { type: "image/png" });
    fireEvent.drop(dropzone, { dataTransfer: { files: [file] } });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Remove x.png" })).not.toBeInTheDocument();
  });

  it("renders custom dropzone content (escape hatch)", () => {
    render(<FileUpload>Drop your avatar</FileUpload>);
    expect(screen.getByRole("button", { name: "Drop your avatar" })).toBeInTheDocument();
  });
});
