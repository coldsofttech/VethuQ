import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CodeViewer, LANGUAGES, codeMode, keyBefore } from "./index.js";

const JSON_TEXT = '{\n  "name": "wheat",\n  "port": 80\n}\n';

describe("codeMode", () => {
  it("opens a file as its source, and a minified one laid out when it can be", () => {
    expect(codeMode("json", JSON_TEXT, 12, null)).toEqual({
      mode: "source",
      canFormat: true,
      tooBig: false,
    });
    expect(codeMode("json", JSON_TEXT, 5000, null).mode).toBe("formatted");
  });

  it("keeps the person’s choice, and a language without a layout as source", () => {
    expect(codeMode("json", JSON_TEXT, 5000, "source").mode).toBe("source");
    expect(codeMode("json", JSON_TEXT, 5, "formatted").mode).toBe("formatted");
    expect(codeMode("toml", "a = 1", 5000, null)).toEqual({
      mode: "source",
      canFormat: false,
      tooBig: false,
    });
  });

  it("does not lay out a file that is too large", () => {
    const big = "x".repeat(20 * 1024 * 1024 + 1);
    expect(codeMode("json", big, 10, "formatted")).toEqual({
      mode: "source",
      canFormat: false,
      tooBig: true,
    });
  });
});

describe("keyBefore", () => {
  it("is the last name of the path a value sits under", () => {
    expect(keyBefore("server.ports[0]: ")).toBe("ports");
    expect(keyBefore("catalog/book@id: ")).toBe("id");
    expect(keyBefore("no key here")).toBeNull();
  });
});

describe("LANGUAGES", () => {
  it("names every language the code preview shows", () => {
    expect(Object.keys(LANGUAGES).sort()).toEqual(
      ["css", "js", "json", "ndjson", "toml", "xml", "yaml"].sort(),
    );
    for (const spec of Object.values(LANGUAGES)) {
      expect(spec.label).toBeTruthy();
      expect(typeof spec.hint).toBe("function");
    }
  });
});

describe("CodeViewer", () => {
  it("says where the match is in the text it shows", async () => {
    const onLocated = vi.fn();
    render(
      <div style={{ height: 300 }}>
        <CodeViewer
          text={JSON_TEXT}
          language="json"
          match={{ before: "name: ", matched: "wheat", after: "" }}
          onLocated={onLocated}
        />
      </div>,
    );
    await waitFor(() => expect(onLocated).toHaveBeenCalled());
    expect(onLocated.mock.calls.at(-1)[0]).toMatchObject({ line: 2 });
  });

  it("says null when the words are not there", async () => {
    const onLocated = vi.fn();
    render(
      <div style={{ height: 300 }}>
        <CodeViewer
          text={JSON_TEXT}
          language="json"
          match={{ before: "", matched: "barley", after: "" }}
          onLocated={onLocated}
        />
      </div>,
    );
    await waitFor(() => expect(onLocated).toHaveBeenCalledWith(null));
  });
});
