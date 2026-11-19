import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Card, Feed } from "./types";
import { filterCards, isFeed, readStoredIds, storeIds } from "./feed";
import type { CategoryFilter, TimeFilter } from "./feed";
import { FeedCard } from "./components/FeedCard";
import { SafeLink } from "./components/CardVisual";
import { TopBar } from "./components/TopBar";
import { readProgress, resumeIndex, storeProgress, unreadCards } from "./progress";

const SAVED_KEY = "spark:saved";
const DISMISSED_KEY = "spark:dismissed";

interface SavedViewProps {
  cards: Card[];
  onRemove: (id: string) => void;
}

/** List saved feed cards with a direct remove action. */
function SavedView({ cards, onRemove }: SavedViewProps): React.JSX.Element {
  return (
    <section className="saved-view" aria-label="Saved cards">
      <div className="saved-heading">
        <span className="eyebrow">Your reading list</span>
        <h1>Saved sparks</h1>
        <p>Keep the ideas you want to return to.</p>
      </div>
      {cards.length === 0 ? (
        <div className="saved-empty">
          Nothing saved yet. Save a card from the feed to find it here.
        </div>
      ) : (
        <ul className="saved-list">
          {cards.map((card) => (
            <li key={card.id} data-category={card.category}>
              <span className="saved-category">
                {card.category} · {card.mins} min
              </span>
              <h2>{card.hook}</h2>
              <div className="saved-row">
                <SafeLink source={card.source} className="saved-source">
                  Read original
                </SafeLink>
                <button
                  type="button"
                  aria-label={`Remove saved: ${card.hook}`}
                  onClick={() => onRemove(card.id)}
                >
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Fetch the generated feed, manage local actions, and render the swipe feed. */
export default function App(): React.JSX.Element {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [retry, setRetry] = useState(0);
  const [time, setTime] = useState<TimeFilter>("All");
  const [category, setCategory] = useState<CategoryFilter>("All");
  const [saved, setSaved] = useState<Set<string>>(readStoredIds(SAVED_KEY));
  const [dismissed, setDismissed] = useState<Set<string>>(
    readStoredIds(DISMISSED_KEY),
  );
  const [savedOpen, setSavedOpen] = useState(false);
  const [current, setCurrent] = useState(1);
  const [initialProgress] = useState(readProgress);
  const progress = useRef(initialProgress);
  const [readIds, setReadIds] = useState(() => new Set(initialProgress.readIds));
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    /** Load and validate the feed; the effect's abort signal is input; return nothing. */
    async function loadFeed(): Promise<void> {
      setStatus("loading");
      try {
        const response = await fetch("/feed.json", {
          cache: "no-cache",
          signal: controller.signal,
        });
        if (!response.ok)
          throw new Error(`Feed request failed: ${response.status}`);
        const value: unknown = await response.json();
        if (!isFeed(value))
          throw new Error("Feed JSON has an unsupported shape");
        setFeed(value);
        setStatus("ready");
      } catch {
        if (!controller.signal.aborted) setStatus("error");
      }
    }
    void loadFeed();
    return () => controller.abort();
  }, [retry]);

  const visible = useMemo(
    () => filterCards(feed?.cards ?? [], time, category, dismissed),
    [feed, time, category, dismissed],
  );
  const unread = unreadCards(visible, readIds);
  const savedCards = (feed?.cards ?? []).filter((card) => saved.has(card.id));

  useLayoutEffect(() => {
    const root = scrollRef.current;
    if (!root || savedOpen || status !== "ready") return;
    const index = resumeIndex(visible, progress.current);
    const panel = root.children.item(index);
    if (panel instanceof HTMLElement) root.scrollTop = panel.offsetTop;
    setCurrent(index + 1);
    const id = visible[index]?.id;
    if (id && id !== progress.current.activeId) {
      progress.current = { ...progress.current, activeId: id };
      storeProgress(progress.current);
    }
  }, [visible, savedOpen, status]);

  /** Track the card crossing the center of the feed and persist its stable ID. */
  function trackPosition(): void {
    const root = scrollRef.current;
    if (!root) return;
    const position = root.scrollTop + root.clientHeight / 2;
    // Panels are ordered by offset, so this also works for cards taller than the viewport.
    let low = 0;
    let high = root.children.length - 1;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      const panel = root.children.item(middle);
      if (panel instanceof HTMLElement && panel.offsetTop <= position) low = middle;
      else high = middle - 1;
    }
    setCurrent(low + 1);
    const id = visible[low]?.id;
    if (id && id !== progress.current.activeId) {
      progress.current = { ...progress.current, activeId: id };
      storeProgress(progress.current);
    }
  }

  /** Toggle read status for a story and store the updated IDs. */
  function toggleRead(id: string): void {
    const next = new Set(readIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    progress.current = { ...progress.current, readIds: [...next] };
    storeProgress(progress.current);
    setReadIds(next);
  }

  /** Scroll to a rendered panel and move keyboard focus to it. */
  function goToPanel(index: number): void {
    const root = scrollRef.current;
    const panel = root?.children.item(index);
    if (!root || !(panel instanceof HTMLElement)) return;
    root.scrollTop = panel.offsetTop;
    panel.focus({ preventScroll: true });
    trackPosition();
  }

  /** Mark the chosen story read and advance to the following panel. */
  function readAndNext(id: string): void {
    if (!readIds.has(id)) toggleRead(id);
    goToPanel(visible.findIndex((card) => card.id === id) + 1);
  }

  /** Toggle one saved ID and try to persist the new set; id is input; return nothing. */
  function toggleSaved(id: string): void {
    const next = new Set(saved);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSaved(next);
    storeIds(SAVED_KEY, next);
  }

  /** Hide one card and try to persist its ID; id is input; return nothing. */
  function dismiss(id: string): void {
    const next = new Set(dismissed);
    next.add(id);
    setDismissed(next);
    storeIds(DISMISSED_KEY, next);
  }

  /** Restore all hidden cards; take no args and return nothing. */
  function restoreDismissed(): void {
    const next = new Set<string>();
    setDismissed(next);
    storeIds(DISMISSED_KEY, next);
  }

  /** Speak a headline and body with the browser voice; card is input; return nothing. */
  function listen(card: Card): void {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(
      new SpeechSynthesisUtterance(`${card.hook}. ${card.body}`),
    );
  }

  /** Trigger another feed request; take no args and return nothing. */
  function retryFeed(): void {
    setRetry((value) => value + 1);
  }

  /** Switch between feed and saved cards; take no args and return nothing. */
  function toggleSavedView(): void {
    setSavedOpen((open) => !open);
  }

  return (
    <div className="app-shell">
      <TopBar
        time={time}
        category={category}
        current={current}
        total={visible.length}
        unread={unread.length}
        savedCount={savedCards.length}
        savedOpen={savedOpen}
        onTime={setTime}
        onCategory={setCategory}
        onSaved={toggleSavedView}
      />
      {savedOpen ? (
        <SavedView cards={savedCards} onRemove={toggleSaved} />
      ) : status === "loading" ? (
        <main className="state-panel" aria-live="polite">
          <span className="eyebrow">Spark feed</span>
          <h1>Finding your next spark…</h1>
          <p>Loading the latest stories.</p>
        </main>
      ) : status === "error" ? (
        <main className="state-panel" aria-live="polite">
          <span className="eyebrow">Feed unavailable</span>
          <h1>Couldn’t load the feed.</h1>
          <p>Check your connection and try again.</p>
          <button
            type="button"
            onClick={retryFeed}
            aria-label="Retry loading feed"
          >
            Retry
          </button>
        </main>
      ) : visible.length === 0 ? (
        <main className="state-panel" aria-live="polite">
          <span className="eyebrow">Nothing here yet</span>
          <h1>No sparks in this view.</h1>
          <p>Try another filter, restore hidden cards, or reload the feed.</p>
          <div className="state-actions">
            {dismissed.size > 0 && (
              <button
                type="button"
                onClick={restoreDismissed}
                aria-label="Show hidden cards"
              >
                Show hidden cards
              </button>
            )}
            <button
              type="button"
              onClick={retryFeed}
              aria-label="Retry loading feed"
            >
              Retry
            </button>
          </div>
        </main>
      ) : (
        <main
          ref={scrollRef}
          className="feed-scroll"
          onScroll={trackPosition}
          aria-label="Learning feed"
        >
          {visible.map((card, index) => (
            <FeedCard
              key={card.id}
              card={card}
              index={index + 1}
              saved={saved.has(card.id)}
              read={readIds.has(card.id)}
              onRead={toggleRead}
              onReadAndNext={readAndNext}
              onSave={toggleSaved}
              onDismiss={dismiss}
              onListen={listen}
            />
          ))}
          <section
            className="caught-up snap-panel"
            data-index={visible.length + 1}
            aria-label="End of feed"
            tabIndex={-1}
          >
            <div className="caught-up-inner">
              <h2>{unread.length ? "End of this view." : "You’re caught up."}</h2>
              {unread.length > 0 && (
                <button type="button" onClick={() => goToPanel(visible.indexOf(unread[0]))}>
                  Back to unread
                </button>
              )}
              <button
                type="button"
                onClick={retryFeed}
                aria-label="Refresh the feed"
              >
                Refresh feed
              </button>
            </div>
          </section>
        </main>
      )}
    </div>
  );
}
