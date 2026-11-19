import { afterEach, describe, expect, it, vi } from "vitest";
import { readProgress, resumeIndex, storeProgress, unreadCards } from "./progress";
import type { ReadingProgress } from "./progress";

const progress: ReadingProgress = { version: 1, readIds: ["read"], activeId: "active" };

afterEach(() => { vi.unstubAllGlobals(); });

describe("local reading progress", () => {
  it("round trips progress through storage", () => {
    let value = "";
    vi.stubGlobal("localStorage", {
      getItem: () => value,
      setItem: (_key: string, next: string) => { value = next; },
    });
    storeProgress(progress);
    expect(readProgress()).toEqual(progress);
  });

  it("recovers from corrupt or unavailable storage", () => {
    const empty = { version: 1, readIds: [], activeId: null };
    vi.stubGlobal("localStorage", { getItem: () => "{" });
    expect(readProgress()).toEqual(empty);
    vi.stubGlobal("localStorage", undefined);
    expect(readProgress()).toEqual(empty);
    expect(() => storeProgress(progress)).not.toThrow();
  });

  it("resumes by ID after reordering and falls back to the first unread story", () => {
    expect(resumeIndex([{ id: "new" }, { id: "active" }], progress)).toBe(1);
    expect(resumeIndex([{ id: "read" }, { id: "new" }], progress)).toBe(1);
    expect(resumeIndex([{ id: "read" }], progress)).toBe(0);
  });
});

it("counts unread stories in the supplied filtered view", () => {
  const readIds = new Set(["read", "elsewhere"]);
  expect(unreadCards([{ id: "read" }, { id: "skipped" }], readIds))
    .toEqual([{ id: "skipped" }]);
});
