export type Category = "AI" | "Development" | "CVEs" | "Cyber Security";

export interface CardSource {
  name: string;
  url: string;
}

export interface CveDetails {
  id: string;
  cvss: number | null;
  severity: string;
  affected: string;
  exploited: string;
  fix: string;
}

export interface Card {
  id: string;
  category: Category;
  type: string;
  hook: string;
  body: string;
  mins: number;
  source: CardSource;
  published: string;
  rank: number;
  cve?: CveDetails;
  via?: CardSource;
  meta?: Record<string, unknown>;
}

export interface Feed {
  version: 1;
  generated_at: string;
  cards: Card[];
}
