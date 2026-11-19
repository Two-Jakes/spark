import type { Card, Category, Feed } from "./types";

export type TimeFilter = "All" | 2 | 5 | 10;
export type CategoryFilter = Category | "All";

/** Return cards matching time, category, and dismissal filters. */
export function filterCards(
  cards: Card[],
  time: TimeFilter,
  category: CategoryFilter,
  dismissed: ReadonlySet<string>,
): Card[] {
  return cards.filter(
    (card) =>
      !dismissed.has(card.id) &&
      (time === "All" || card.mins === time) &&
      (category === "All" || card.category === category),
  );
}

/** Accept only absolute HTTP(S) URLs for links rendered from the feed. */
export function safeHttpUrl(value: string): string | null {
  if (!value.startsWith("http://") && !value.startsWith("https://"))
    return null;
  try {
    const url = new URL(value);
    return url.hostname && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

/** Read a stored ID set, returning an empty set when browser storage is unavailable. */
export function readStoredIds(key: string): Set<string> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) ?? "[]");
    return new Set(
      Array.isArray(value)
        ? value.filter((id): id is string => typeof id === "string")
        : [],
    );
  } catch {
    return new Set();
  }
}

/** Persist an ID set and keep the UI usable when browser storage fails. */
export function storeIds(key: string, ids: ReadonlySet<string>): void {
  try {
    localStorage.setItem(key, JSON.stringify([...ids]));
  } catch {
    // In-memory state still works when storage is blocked.
  }
}

/** Check the minimum version 1 feed shape before rendering remote JSON. */
export function isFeed(value: unknown): value is Feed {
  if (typeof value !== "object" || value === null) return false;
  const feed = value as Record<string, unknown>;
  return (
    feed.version === 1 &&
    typeof feed.generated_at === "string" &&
    Array.isArray(feed.cards) &&
    feed.cards.every(isCard)
  );
}

/** Check a name and URL pair; value is unknown and return is a source type guard. */
function isSource(value: unknown): boolean {
  if (typeof value !== "object" || value === null) return false;
  const source = value as Record<string, unknown>;
  return typeof source.name === "string" && typeof source.url === "string";
}

/** Check advisory fields before the visual reads them; value is unknown; return validity. */
function isCve(value: unknown): boolean {
  if (typeof value !== "object" || value === null) return false;
  const cve = value as Record<string, unknown>;
  return (
    typeof cve.id === "string" &&
    (cve.cvss === null || typeof cve.cvss === "number") &&
    typeof cve.severity === "string" &&
    typeof cve.affected === "string" &&
    typeof cve.exploited === "string" &&
    typeof cve.fix === "string"
  );
}

/** Check fields the UI reads from one card; value is unknown and return is a type guard. */
export function isCard(value: unknown): value is Card {
  if (typeof value !== "object" || value === null) return false;
  const card = value as Record<string, unknown>;
  return (
    typeof card.id === "string" &&
    ["AI", "Development", "CVEs", "Cyber Security"].includes(
      String(card.category),
    ) &&
    typeof card.type === "string" &&
    typeof card.hook === "string" &&
    typeof card.body === "string" &&
    typeof card.mins === "number" &&
    typeof card.published === "string" &&
    typeof card.rank === "number" &&
    isSource(card.source) &&
    (card.via === undefined || isSource(card.via)) &&
    (card.cve === undefined || isCve(card.cve)) &&
    (card.meta === undefined ||
      (typeof card.meta === "object" &&
        card.meta !== null &&
        !Array.isArray(card.meta)))
  );
}
