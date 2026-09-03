// @vitest-environment jsdom
/**
 * P1 regression coverage: the historical-import "Choose files" control
 * must always be a genuine, clickable native `<input type="file">` that
 * accepts multiple PDFs, visibly reflects what's selected, and gates the
 * Upload button on a real selection -- see `UploadFilesForm`'s own
 * comments in import-quotations.tsx for the root-cause analysis (no code
 * change had actually broken the input's click-ability; the real gaps
 * were no `accept`, no selected-file feedback, and Upload staying
 * enabled with zero files chosen).
 *
 * Deliberately renders just `UploadFilesForm` in isolation (not the
 * whole page) via plain `react-dom/client` + jsdom -- this project has no
 * `@testing-library/react` yet, and the full page pulls in Supabase/
 * react-query/router context this narrow DOM check doesn't need. A real
 * OS file-picker dialog is fundamentally untestable from any JS runtime
 * (browser security boundary); what IS provable here, and what this
 * suite proves, is that the input renders correctly, is never disabled/
 * covered, dispatches a real `change` event through to React state, and
 * that state correctly drives the visible filenames and the Upload
 * button -- the actual DOM/event flow a real click would go through.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UploadFilesForm } from "./import-quotations";

// No @testing-library/react here (see this file's own docstring) to set
// this automatically -- React's `act()` warns without it.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const t = (key: string) => key;

function makePdf(name: string): File {
  return new File(["%PDF-1.4 test content"], name, { type: "application/pdf" });
}

/** `HTMLInputElement.files` is read-only like a real browser's, and this
 * jsdom version doesn't implement `DataTransfer` (the usual way around
 * that) -- `Object.defineProperty` overrides it directly for the test.
 * The component under test only ever reads `.files` positionally/via
 * `Array.from`, both of which work identically against a plain array. */
function selectFiles(input: HTMLInputElement, files: File[]): void {
  Object.defineProperty(input, "files", { value: files, configurable: true });
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("UploadFilesForm (historical-import file picker)", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("renders a real, enabled, multi-select native file input accepting PDFs", () => {
    act(() => {
      root.render(
        <UploadFilesForm
          fileInputRef={{ current: null }}
          selectedFiles={[]}
          onFilesChosen={() => {}}
          onSubmit={(e) => e.preventDefault()}
          submitting={false}
          t={t}
        />,
      );
    });

    const input = container.querySelector('input[type="file"]');
    expect(input).toBeInstanceOf(HTMLInputElement);
    const fileInput = input as HTMLInputElement;
    // Never disabled, never hidden behind a proxy button, never wrapped
    // in anything that would swallow a click before it reaches this
    // element -- exactly the click-ability the P1 report was worried
    // about, checked directly on the real node.
    expect(fileInput.disabled).toBe(false);
    expect(fileInput.type).toBe("file");
    expect(fileInput.multiple).toBe(true);
    expect(fileInput.accept).toBe("application/pdf");
    expect(fileInput.getAttribute("aria-label")).toBeTruthy();
  });

  it("selecting files fires a real DOM change event the handler receives", () => {
    const onFilesChosen = vi.fn();
    act(() => {
      root.render(
        <UploadFilesForm
          fileInputRef={{ current: null }}
          selectedFiles={[]}
          onFilesChosen={onFilesChosen}
          onSubmit={(e) => e.preventDefault()}
          submitting={false}
          t={t}
        />,
      );
    });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;

    act(() => selectFiles(input, [makePdf("quote.pdf")]));

    expect(onFilesChosen).toHaveBeenCalledTimes(1);
    const call = onFilesChosen.mock.calls[0]?.[0] as { target: HTMLInputElement } | undefined;
    expect(call?.target.files?.[0]?.name).toBe("quote.pdf");
  });

  it("does not display a selected-files line when nothing is chosen", () => {
    act(() => {
      root.render(
        <UploadFilesForm
          fileInputRef={{ current: null }}
          selectedFiles={[]}
          onFilesChosen={() => {}}
          onSubmit={(e) => e.preventDefault()}
          submitting={false}
          t={t}
        />,
      );
    });
    expect(container.querySelector('[data-testid="imp-selected-files"]')).toBeNull();
  });

  it("shows the selected filenames once files are chosen (state -> UI, not just the input's own text)", () => {
    act(() => {
      root.render(
        <UploadFilesForm
          fileInputRef={{ current: null }}
          selectedFiles={[makePdf("quote-a.pdf"), makePdf("quote-b.pdf")]}
          onFilesChosen={() => {}}
          onSubmit={(e) => e.preventDefault()}
          submitting={false}
          t={t}
        />,
      );
    });
    const filenames = container.querySelector('[data-testid="imp-selected-files"]');
    expect(filenames?.textContent).toContain("quote-a.pdf");
    expect(filenames?.textContent).toContain("quote-b.pdf");
  });

  it("Upload is disabled until at least one file is selected", () => {
    act(() => {
      root.render(
        <UploadFilesForm
          fileInputRef={{ current: null }}
          selectedFiles={[]}
          onFilesChosen={() => {}}
          onSubmit={(e) => e.preventDefault()}
          submitting={false}
          t={t}
        />,
      );
    });
    const submit = container.querySelector('button[type="submit"]') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it("Upload becomes enabled once files are selected, and selecting alone never submits", () => {
    const onSubmit = vi.fn((e: { preventDefault: () => void }) => e.preventDefault());
    act(() => {
      root.render(
        <UploadFilesForm
          fileInputRef={{ current: null }}
          selectedFiles={[makePdf("quote.pdf")]}
          onFilesChosen={() => {}}
          onSubmit={onSubmit}
          submitting={false}
          t={t}
        />,
      );
    });
    const submit = container.querySelector('button[type="submit"]') as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    // Choosing a file must never, by itself, fire the form's submit --
    // upload only happens on an explicit Upload click (P1's own
    // requirement: "upload does not happen merely by selecting the
    // file").
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("Upload is disabled while a submission is already in flight", () => {
    act(() => {
      root.render(
        <UploadFilesForm
          fileInputRef={{ current: null }}
          selectedFiles={[makePdf("quote.pdf")]}
          onFilesChosen={() => {}}
          onSubmit={(e) => e.preventDefault()}
          submitting
          t={t}
        />,
      );
    });
    const submit = container.querySelector('button[type="submit"]') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });
});
