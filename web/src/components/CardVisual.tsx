import type { Card, CardSource } from "../types";
import { safeHttpUrl } from "../feed";

interface SafeLinkProps {
  source: CardSource;
  className?: string;
  children: React.ReactNode;
}

/** Render a trusted external link, or plain text when its URL is unsafe. */
export function SafeLink({
  source,
  className,
  children,
}: SafeLinkProps): React.JSX.Element {
  const href = safeHttpUrl(source.url);
  if (!href) return <span className={className}>{children}</span>;
  return (
    <a
      className={className}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
    </a>
  );
}

interface VisualProps {
  card: Card;
}

/** Show CVSS and the three actionable details for an advisory card. */
function AdvisoryVisual({ card }: VisualProps): React.JSX.Element {
  const cve = card.cve;
  if (!cve) return <ArticleVisual card={card} />;
  return (
    <div className="advisory-visual" data-layout="advisory">
      <div className="advisory-score-line">
        <div
          className="cvss-circle"
          aria-label={
            cve.cvss === null
              ? "CVSS score unavailable"
              : `CVSS score ${cve.cvss.toFixed(1)}`
          }
        >
          <strong>{cve.cvss === null ? "—" : cve.cvss.toFixed(1)}</strong>
          <span>CVSS</span>
        </div>
        <div className="advisory-identity">
          <span className="severity">{cve.severity}</span>
          <code>{cve.id}</code>
        </div>
      </div>
      <dl className="advisory-facts">
        <div>
          <dt>Affected</dt>
          <dd>{cve.affected}</dd>
        </div>
        <div>
          <dt>Exploited</dt>
          <dd>{cve.exploited}</dd>
        </div>
        <div>
          <dt>Fix</dt>
          <dd>{cve.fix}</dd>
        </div>
      </dl>
      <p className="card-body">{card.body}</p>
    </div>
  );
}

/** Show a paper abstract as a distinct reading block. */
function PaperVisual({ card }: VisualProps): React.JSX.Element {
  return (
    <div className="paper-visual" data-layout="paper">
      <span className="visual-kicker">Abstract snippet</span>
      <p>{card.body}</p>
    </div>
  );
}

/** Show article copy for links and any future unrecognized card type. */
function ArticleVisual({ card }: VisualProps): React.JSX.Element {
  return (
    <div className="article-visual" data-layout="article">
      <p className="card-body">{card.body}</p>
    </div>
  );
}

/** Select a visual by card type, safely falling back to the article layout. */
export function CardVisual({ card }: VisualProps): React.JSX.Element {
  if (card.type === "advisory") return <AdvisoryVisual card={card} />;
  if (card.type === "paper") return <PaperVisual card={card} />;
  return <ArticleVisual card={card} />;
}
