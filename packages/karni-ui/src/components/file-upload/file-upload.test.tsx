import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FileUpload, defaultFileUploadSlots, type FileUploadFileRowProps } from "./FileUpload";

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

describe("FileUpload accessibility", () => {
  it("is named by a <label htmlFor> and opens the picker from the keyboard", async () => {
    const user = userEvent.setup();
    const click = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => {});
    render(
      <>
        <label htmlFor="cover">Cover image</label>
        <FileUpload id="cover" />
      </>,
    );
    const dropzone = screen.getByRole("button", { name: "Cover image" });
    await user.tab();
    expect(dropzone).toHaveFocus();
    await user.keyboard("{Enter}");
    await user.keyboard(" ");
    expect(click).toHaveBeenCalledTimes(2);
  });

  it("announces a refused file and links the message to the dropzone", () => {
    render(<FileUpload accept=".png" maxSize={3} aria-describedby="help" />);
    const dropzone = screen.getByRole("button", { name: /click to browse/ });
    expect(dropzone).toHaveAttribute("aria-describedby", "help");

    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [
          new File(["x"], "notes.txt", { type: "text/plain" }),
          new File(["12345"], "big.png", { type: "image/png" }),
        ],
      },
    });
    const alerts = screen.getAllByRole("alert");
    expect(alerts.map((alert) => alert.textContent)).toEqual([
      "notes.txt isn't an accepted file type.",
      "big.png is larger than 3 B.",
    ]);
    const messageId = alerts[0]?.parentElement?.id ?? "";
    expect(dropzone.getAttribute("aria-describedby")).toBe(`help ${messageId}`);
    // A refusal is not a field error.
    expect(dropzone).not.toHaveAttribute("aria-invalid");

    // A good file clears the refusals.
    fireEvent.drop(dropzone, {
      dataTransfer: { files: [new File(["ok"], "ok.png", { type: "image/png" })] },
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("rejectionMessage rewords refusals, or silences them with null", () => {
    const { rerender } = render(
      <FileUpload accept=".png" rejectionMessage={(file) => `Nope: ${file.name}`} />,
    );
    const drop = (): void => {
      fireEvent.drop(screen.getByRole("button"), {
        dataTransfer: { files: [new File(["x"], "a.txt", { type: "text/plain" })] },
      });
    };
    drop();
    expect(screen.getByRole("alert")).toHaveTextContent("Nope: a.txt");
    rerender(<FileUpload accept=".png" rejectionMessage={() => null} />);
    drop();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the error prop, announced, and marks the dropzone invalid", () => {
    render(<FileUpload error="Choose a cover image." aria-label="Cover" />);
    const dropzone = screen.getByRole("button", { name: "Cover" });
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a cover image.");
    expect(dropzone).toHaveAttribute("aria-invalid", "true");
    expect(dropzone).toHaveAccessibleDescription("Choose a cover image.");
    expect(dropzone).toHaveClass("aria-[invalid=true]:border-destructive");
  });

  it("passes aria-invalid and aria-labelledby through (a form's own error message)", () => {
    render(
      <>
        <span id="lbl">Attachment</span>
        <FileUpload aria-labelledby="lbl" aria-invalid aria-describedby="err" />
      </>,
    );
    const dropzone = screen.getByRole("button", { name: "Attachment" });
    expect(dropzone).toHaveAttribute("aria-invalid", "true");
    expect(dropzone).toHaveAttribute("aria-describedby", "err");
  });

  it("shows progress while uploading and takes no new files", () => {
    const onChange = vi.fn();
    render(
      <FileUpload
        uploading
        onChange={onChange}
        value={new File(["a"], "a.png", { type: "image/png" })}
      />,
    );
    const dropzone = screen.getByRole("button", { name: /uploading/i });
    expect(dropzone).toBeDisabled();
    expect(dropzone).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Uploading…");
    expect(screen.queryByRole("button", { name: "Remove a.png" })).not.toBeInTheDocument();
    fireEvent.drop(dropzone, {
      dataTransfer: { files: [new File(["b"], "b.png", { type: "image/png" })] },
    });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("returns focus to the dropzone after a file is removed", async () => {
    const user = userEvent.setup();
    render(<FileUpload value="https://files.example.com/launch.png" onChange={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Remove launch.png" }));
    expect(screen.getByRole("button", { name: /click to browse/ })).toHaveFocus();
  });

  it("slots replace the dropzone and the file rows", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    function Row({ name, size, onRemove }: FileUploadFileRowProps) {
      return (
        <li data-testid="row">
          {name} ({size})
          {onRemove && (
            <button type="button" onClick={onRemove}>
              Drop {name}
            </button>
          )}
        </li>
      );
    }
    render(
      <FileUpload
        value={new File(["abc"], "a.png", { type: "image/png" })}
        onChange={onChange}
        slots={{
          FileRow: Row,
          Dropzone: (props) => (
            <div data-testid="zone">
              <defaultFileUploadSlots.Dropzone {...props}>Pick one</defaultFileUploadSlots.Dropzone>
            </div>
          ),
        }}
      />,
    );
    expect(screen.getByTestId("zone")).toContainElement(
      screen.getByRole("button", { name: "Pick one" }),
    );
    expect(screen.getByTestId("row")).toHaveTextContent("a.png (3 B)");
    await user.click(screen.getByRole("button", { name: "Drop a.png" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
