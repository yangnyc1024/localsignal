import { ArrowUpRight, Flame } from "lucide-react";

import type { FoodSignal, SignalEvidenceItem } from "@/lib/types";
import { cleanText, formatDateTime, truncateEvidence } from "../_utils";

type Props = {
  foodSignal: FoodSignal | undefined;
  evidence: SignalEvidenceItem[];
};

export function WhatsMovingSection({ foodSignal, evidence }: Props) {
  const dish = cleanText(foodSignal?.signal_dish || foodSignal?.primary_pull || "");
  const occasion = cleanText(foodSignal?.occasion || "");
  const topEvidence = evidence.slice(0, 3);

  return (
    <section className="rounded-lg border border-line bg-white/88 p-5 shadow-sm md:p-6">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-normal text-ink/60">
        <Flame size={17} className="text-moss" />
        What&rsquo;s moving this week
      </h2>
      <div className="grid gap-5">
        {dish ? (
          <div className="rounded-lg border border-moss/25 bg-moss/6 p-4 md:p-5">
            <div className="text-xs font-semibold uppercase tracking-normal text-moss">Most talked about</div>
            <div className="mt-2 text-xl font-semibold leading-7 text-ink">{dish}</div>
            {occasion ? (
              <div className="mt-1 text-sm leading-6 text-ink/60">{occasion}</div>
            ) : null}
          </div>
        ) : null}

        {topEvidence.length > 0 ? (
          <div className="grid gap-3">
            <div className="text-xs font-semibold uppercase tracking-normal text-ink/48">Recent voices</div>
            {topEvidence.map((item) => (
              <div key={`${item.platform}-${item.timestamp}`} className="rounded-lg border border-line bg-paper p-4">
                <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-moss">
                  <span>{item.platform}</span>
                  <span className="text-ink/40">·</span>
                  <span className="text-ink/50">{formatDateTime(item.timestamp)}</span>
                </div>
                <p className="mt-2 text-sm leading-6 text-ink/76">
                  &ldquo;{truncateEvidence(item.excerpt, 200)}&rdquo;
                </p>
                {item.source_url ? (
                  <a href={item.source_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-clay hover:underline">
                    Source <ArrowUpRight size={11} />
                  </a>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
