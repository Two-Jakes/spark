import { afterEach, expect, it, vi } from "vitest";
import { readLibrary, recoverSavedCards, storeLibrary } from "./saved";
import type { Card } from "./types";

afterEach(() => { vi.unstubAllGlobals(); });

it("keeps saved stories locally after they rotate out of the feed", () => {
  const storage = new Map([["spark:saved", '["old","missing"]']]);
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key),
    setItem: (key: string, value: string) => storage.set(key, value),
  });
  const story: Card = {
    id: "old", category: "Development", type: "article", hook: "Headline",
    body: "Summary", mins: 2, source: { name: "Publisher", url: "https://example.com" },
    published: "2026-11-19T00:00:00Z", rank: 1,
  };
  storeLibrary(recoverSavedCards(readLibrary(), [story]));
  expect(recoverSavedCards(readLibrary(), []).get("old")).toEqual(story);
  expect(readLibrary().get("missing")).toBeNull();

  const saved = readLibrary();
  saved.delete("old");
  storeLibrary(saved);
  expect(readLibrary().has("old")).toBe(false);
});
