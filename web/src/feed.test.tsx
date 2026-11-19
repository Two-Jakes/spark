import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SafeLink } from "./components/CardVisual";
import { FeedCard } from "./components/FeedCard";
import { filterCards, safeHttpUrl } from "./feed";
import type { Card } from "./types";

const cards: Card[] = [
  {
    id: "one",
    category: "AI",
    type: "paper",
    hook: "One",
    body: "Abstract.",
    mins: 5,
    source: { name: "arXiv", url: "https://arxiv.org/abs/1" },
    published: "2026-11-18T00:00:00Z",
    rank: 3,
  },
  {
    id: "two",
    category: "Development",
    type: "article",
    hook: "Two",
    body: "Story.",
    mins: 2,
    source: { name: "Example", url: "https://example.com/two" },
    published: "2026-11-18T00:00:00Z",
    rank: 2,
  },
  {
    id: "three",
    category: "AI",
    type: "article",
    hook: "Three",
    body: "Story.",
    mins: 10,
    source: { name: "Example", url: "https://example.com/three" },
    published: "2026-11-18T00:00:00Z",
    rank: 1,
  },
];

describe("feed selection and rendering", () => {
  /** Check exact reading-time filters and the All option; return nothing. */
  it("filters by reading time", () => {
    expect(
      filterCards(cards, 2, "All", new Set()).map((card) => card.id),
    ).toEqual(["two"]);
    expect(
      filterCards(cards, 5, "All", new Set()).map((card) => card.id),
    ).toEqual(["one"]);
    expect(
      filterCards(cards, 10, "All", new Set()).map((card) => card.id),
    ).toEqual(["three"]);
    expect(filterCards(cards, "All", "All", new Set())).toHaveLength(3);
  });

  /** Check category and dismissed-ID filters together; return nothing. */
  it("filters by category and dismissed ids", () => {
    expect(
      filterCards(cards, "All", "AI", new Set(["one"])).map((card) => card.id),
    ).toEqual(["three"]);
    expect(filterCards(cards, "All", "Development", new Set())).toHaveLength(1);
  });

  /** Check protocol and credential rejection before links reach JSX; return nothing. */
  it("sanitizes external link URLs", () => {
    expect(safeHttpUrl("https://example.com/story")).toBe(
      "https://example.com/story",
    );
    expect(safeHttpUrl("http://example.com/story")).toBe(
      "http://example.com/story",
    );
    expect(safeHttpUrl("javascript:alert(1)")).toBeNull();
    expect(safeHttpUrl("https://user:pass@example.com")).toBeNull();
    expect(safeHttpUrl(" HTTPS://example.com")).toBeNull();
    const html = renderToStaticMarkup(
      createElement(SafeLink, {
        source: { name: "Bad", url: "javascript:alert(1)" },
        children: "Read original",
      }),
    );
    expect(html).not.toContain("href=");
  });

  /** Check that new card types use the article visual and render text safely; return nothing. */
  it("falls back to the article layout for an unknown type", () => {
    const card: Card = {
      ...cards[1],
      type: "future-type",
      body: "<script>alert(1)</script>",
    };
    /** Ignore a card ID in this markup-only test; id is unused; return nothing. */
    function noIdAction(_id: string): void {
      /* No browser action in server rendering. */
    }
    /** Ignore a card in this markup-only test; value is unused; return nothing. */
    function noCardAction(_card: Card): void {
      /* No browser action in server rendering. */
    }
    const html = renderToStaticMarkup(
      createElement(FeedCard, {
        card,
        index: 1,
        saved: false,
        onSave: noIdAction,
        onDismiss: noIdAction,
        onListen: noCardAction,
      }),
    );
    expect(html).toContain('data-layout="article"');
    expect(html).toContain("Read original");
    expect(html).toContain('href="https://example.com/two"');
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
  });
});
