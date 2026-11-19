const PROGRESS_KEY = "spark:progress";

export interface ReadingProgress {
  version: 1;
  readIds: string[];
  activeId: string | null;
}

/** Read local progress, returning an empty record when storage is invalid or unavailable. */
export function readProgress(): ReadingProgress {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(PROGRESS_KEY) ?? "null");
    if (typeof value === "object" && value !== null) {
      const record = value as Record<string, unknown>;
      if (record.version === 1 && Array.isArray(record.readIds)) {
        return {
          version: 1,
          readIds: [...new Set(record.readIds.filter((id): id is string => typeof id === "string"))],
          activeId: typeof record.activeId === "string" ? record.activeId : null,
        };
      }
    }
  } catch {
    // Progress remains available in memory when storage is blocked.
  }
  return { version: 1, readIds: [], activeId: null };
}

/** Persist progress on this device when browser storage is available. */
export function storeProgress(progress: ReadingProgress): void {
  try {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify(progress));
  } catch {
    // Reading remains available in memory when storage is blocked.
  }
}

/** Find the resume index in the visible cards, preferring the last active story. */
export function resumeIndex(
  cards: ReadonlyArray<{ id: string }>,
  progress: ReadingProgress,
): number {
  const active = cards.findIndex((card) => card.id === progress.activeId);
  if (active >= 0) return active;
  const read = new Set(progress.readIds);
  return Math.max(0, cards.findIndex((card) => !read.has(card.id)));
}
