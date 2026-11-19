import { isCard, readStoredIds } from "./feed";
import type { Card } from "./types";

const LIBRARY_KEY = "spark:library";
const LEGACY_KEY = "spark:saved";

export type SavedLibrary = Map<string, Card | null>;

/** Read saved copies and fall back to legacy IDs when no library exists. */
export function readLibrary(): SavedLibrary {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(LIBRARY_KEY) ?? "null");
    if (Array.isArray(value)) {
      const library = new Map<string, Card | null>();
      for (const entry of value) {
        if (typeof entry === "string") library.set(entry, null);
        else if (isCard(entry)) library.set(entry.id, entry);
      }
      return library;
    }
  } catch {
    // Legacy saves may still be readable.
  }
  return new Map(Array.from(readStoredIds(LEGACY_KEY), (id) => [id, null]));
}

/** Store IDs and story copies together so saved stories survive feed rotation. */
export function storeLibrary(library: SavedLibrary): void {
  try {
    const entries = Array.from(library, ([id, card]) => card ?? id);
    localStorage.setItem(LIBRARY_KEY, JSON.stringify(entries));
  } catch {
    // Saved stories can still be used in the current session.
  }
}

/** Fill missing copies for saved IDs present in the latest feed. */
export function recoverSavedCards(library: SavedLibrary, feed: readonly Card[]): SavedLibrary {
  const missing = feed.filter((card) => library.get(card.id) === null);
  return missing.length ? new Map([...library, ...missing.map((card) => [card.id, card] as const)]) : library;
}
