import { ArrowUpRight, Quote } from "lucide-react";

import type { SignalEvidenceItem } from "@/lib/types";
import { cleanText, formatDateTime } from "../_utils";

type Props = {
  evidence: SignalEvidenceItem[];
};

export function EvidenceSection({ evidence }: Props) {
  return (
    <section className="rounded-lg border border-line bg-white/88 p-5 shadow-sm md:p-6">
      <details>
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
          <span className="flex items-center gap-2 text-sm font-semibold uppercase tracking-normal text-ink/60">
            <span className="text-moss"><Quote size={17} /></span>
            Evidence
          </span>
          <span className="rounded-md bg-paper px-2.5 py-1 text-xs font-semibold text-ink/55">
            {evidence.length ? `${evidence.length} snippets` : "Building"}
          </span>
        </summary>
        <div className="mt-4 grid gap-3">
          {evidence.length ? (
            evidence.map((item) => <EvidenceQuote key={`${item.platform}-${item.timestamp}-${item.excerpt}`} item={item} />)
          ) : (
            <p className="rounded-lg border border-line bg-paper p-4 text-sm leading-6 text-ink/66">
              Evidence snippets are still being attached for this signal. Keep this in watching until source receipts are available.
            </p>
          )}
        </div>
      </details>
    </section>
  );
}

function EvidenceQuote({ item }: { item: SignalEvidenceItem }) {
  return (
    <article className="rounded-lg border border-line bg-paper p-4">
      <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-normal text-moss">
        <span className="rounded-md bg-white/80 px-2 py-1 text-ink/60">{item.relevance}</span>
        <span>{item.platform}</span>
        <span>{formatDateTime(item.timestamp)}</span>
      </div>
      <p className="mt-3 text-base leading-7 text-ink/78">"{cleanText(item.excerpt)}"</p>
      {item.source_url ? (
        <a href={item.source_url} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-clay hover:underline">
          Source <ArrowUpRight size={13} />
        </a>
      ) : null}
    </article>
  );
}
