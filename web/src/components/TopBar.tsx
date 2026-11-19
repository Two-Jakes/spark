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
  savedCount,
  savedOpen,
  onTime,
  onCategory,
  onSaved,
}: TopBarProps): React.JSX.Element {
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
          <span className="position-counter" aria-live="polite">
            {total === 0 ? 0 : Math.min(current, total)} / {total}
          </span>
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
        <div className="filter-rows">
          <div className="chip-row" role="group" aria-label="Reading time">
            {TIMES.map((option) => (
              <button
                key={option}
                type="button"
                className="filter-chip"
                aria-label={`Filter reading time: ${option === "All" ? "All" : `${option} minutes`}`}
                aria-pressed={time === option}
                onClick={() => onTime(option)}
              >
                {option === "All" ? "All" : `${option} min`}
              </button>
            ))}
          </div>
          <div
            className="chip-row category-row"
            role="group"
            aria-label="Category"
          >
            {CATEGORIES.map((option) => (
              <button
                key={option}
                type="button"
                className="filter-chip"
                aria-label={`Filter category: ${option}`}
                aria-pressed={category === option}
                onClick={() => onCategory(option)}
              >
                {option}
              </button>
            ))}
          </div>
        </div>
      )}
    </header>
  );
}
