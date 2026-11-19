import type { Card } from "../types";
import { CardVisual, SafeLink } from "./CardVisual";

interface FeedCardProps {
  card: Card;
  index: number;
  saved: boolean;
  read: boolean;
  onRead: (id: string) => void;
  onReadAndNext: (id: string) => void;
  onPrevious?: () => void;
  onSave: (id: string) => void;
  onDismiss: (id: string) => void;
  onListen: (card: Card) => void;
}

/** Render one full-screen feed card and its source and local actions. */
export function FeedCard({
  card,
  index,
  saved,
  read,
  onRead,
  onReadAndNext,
  onPrevious,
  onSave,
  onDismiss,
  onListen,
}: FeedCardProps): React.JSX.Element {
  /** Toggle this card's saved state; return nothing. */
  function handleSave(): void {
    onSave(card.id);
  }
  /** Dismiss this card from the feed; return nothing. */
  function handleDismiss(): void {
    onDismiss(card.id);
  }
  /** Speak this card's headline and body; return nothing. */
  function handleListen(): void {
    onListen(card);
  }

  const publicationDate = new Date(card.published);
  const dateLabel = Number.isNaN(publicationDate.getTime()) ? null
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(publicationDate);

  return (
    <article
      className="feed-card snap-panel"
      data-category={card.category}
      data-index={index}
      tabIndex={-1}
      aria-label={card.hook}
    >
      <div className="card-inner">
        <div className="card-topline">
          <span className="card-tag">
            {card.category} <span aria-hidden="true">·</span> {card.type}{" "}
            <span aria-hidden="true">·</span> {card.mins} min
          </span>
        </div>
        <div className="card-content">
          <h2>{card.hook}</h2>
          <CardVisual card={card} />
        </div>
        <div className="card-bottom">
          <div className="card-links">
            <SafeLink source={card.source} className="read-link">
              {card.source.name}
            </SafeLink>
            {dateLabel && <time dateTime={card.published}>{dateLabel}</time>}
            {card.via && (
              <SafeLink source={card.via} className="via-link">
                via {card.via.name}
              </SafeLink>
            )}
          </div>
          <div className="card-actions">
            {onPrevious && <button type="button" onClick={onPrevious}>Previous</button>}
            <button type="button" onClick={() => onRead(card.id)}>
              {read ? "Mark unread" : "Mark as read"}
            </button>
            <button type="button" onClick={() => onReadAndNext(card.id)}>
              {read ? "Next" : "Read and next"}
            </button>
          </div>
          <div className="card-actions">
            <button
              type="button"
              onClick={handleSave}
              aria-label={`${saved ? "Remove saved" : "Save"}: ${card.hook}`}
              aria-pressed={saved}
            >
              {saved ? "Saved" : "Save"}
            </button>
            <button
              type="button"
              onClick={handleDismiss}
              aria-label={`Not for me: ${card.hook}`}
            >
              Not for me
            </button>
            <button
              type="button"
              onClick={handleListen}
              aria-label={`Listen to: ${card.hook}`}
            >
              Listen
            </button>
          </div>
        </div>
      </div>
    </article>
  );
}
