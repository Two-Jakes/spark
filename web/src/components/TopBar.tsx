import type { CategoryFilter, TimeFilter } from "../feed";

const TIMES: TimeFilter[] = ["All", 2, 5, 10];
const CATEGORIES: CategoryFilter[] = [
  "All",
  "AI",
  "Development",
  "CVEs",
  "Cyber Security",
];

interface TopBarProps {
  time: TimeFilter;
  category: CategoryFilter;
  current: number;
  total: number;
  unread: number;
  savedCount: number;
  savedOpen: boolean;
  onTime: (time: TimeFilter) => void;
  onCategory: (category: CategoryFilter) => void;
  onSaved: () => void;
}

/** Show feed filters, position, and the Saved view control. */
export function TopBar({
  time,
  category,
  current,
  total,
  unread,
  savedCount,
  savedOpen,
  onTime,
  onCategory,
  onSaved,
}: TopBarProps): React.JSX.Element {
  const active = [category === "All" ? null : category, time === "All" ? null : `Up to ${time} min`]
    .filter(Boolean).join(" · ");
  return (
    <header className="top-bar">
      <div className="top-bar-main">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ✦
          </span>
          <span>spark</span>
        </div>
        <div className="top-bar-right">
          {!savedOpen && (
            <span className="position-counter" aria-live="polite">
              {Math.min(current, total)} / {total} · {unread} left
            </span>
          )}
          <button
            className="saved-toggle"
            type="button"
            onClick={onSaved}
            aria-label={`${savedOpen ? "Close" : "Open"} Saved view, ${savedCount} saved cards`}
            aria-pressed={savedOpen}
          >
            Saved <span>{savedCount}</span>
          </button>
        </div>
      </div>
      {!savedOpen && (
        <details className="filters">
          <summary>Filters{active && `: ${active}`}</summary>
          <div className="filter-options">
            <label>
              Topic
              <select value={category} onChange={(event) => onCategory(event.target.value as CategoryFilter)}>
                {CATEGORIES.map((option) => <option key={option}>{option}</option>)}
              </select>
            </label>
            <label>
              Reading time
              <select value={time} onChange={(event) => {
                const selected = TIMES.find((option) => String(option) === event.target.value);
                if (selected !== undefined) onTime(selected);
              }}>
                {TIMES.map((option) => (
                  <option key={option} value={option}>
                    {option === "All" ? "Any length" : `Up to ${option} min`}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" disabled={!active} onClick={() => { onTime("All"); onCategory("All"); }}>
              Reset
            </button>
          </div>
        </details>
      )}
    </header>
  );
}
