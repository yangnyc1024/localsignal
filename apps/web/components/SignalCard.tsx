import { Activity, ArrowUpRight, MapPin, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { SignalActions } from "@/components/SignalActions";
import type { Signal } from "@/lib/types";

type Props = {
  signal: Signal;
  rank: number;
};

export function SignalCard({ signal, rank }: Props) {
  const keywords = signal.evidence.keywords ?? [];
  const sources = signal.evidence.sources ?? [];

  return (
    <article className="grid gap-5 rounded-lg border border-line bg-white/88 p-5 shadow-sm backdrop-blur md:grid-cols-[1fr_180px]">
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-normal text-moss">
          <span>#{rank}</span>
          <span>{labelFor(signal.signal_type)}</span>
          <span>{signal.city}</span>
        </div>

        <h2 className="text-xl font-semibold leading-tight text-ink md:text-2xl">{signal.title}</h2>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-ink/75 md:text-base">{signal.summary}</p>

        <div className="mt-4 flex flex-wrap gap-2">
          {keywords.map((keyword) => (
            <span key={keyword} className="rounded-md bg-paper px-2.5 py-1 text-xs font-medium text-ink">
              {keyword}
            </span>
          ))}
        </div>

        <div className="mt-5 grid gap-3 text-sm text-ink/70 sm:grid-cols-3">
          <Metric icon={<Activity size={16} />} label="Signal Score" value={signal.score.toFixed(1)} />
          <Metric icon={<Sparkles size={16} />} label="Sources" value={sources.length.toString()} />
          <Metric icon={<MapPin size={16} />} label="Place" value={signal.place.neighborhood ?? signal.place.city} />
        </div>
      </div>

      <aside className="flex flex-col justify-between gap-4 rounded-md bg-paper p-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-normal text-ink/50">Place</div>
          <div className="mt-1 font-semibold text-ink">{signal.place.name}</div>
          <div className="mt-1 text-sm capitalize text-ink/65">{signal.place.category}</div>
        </div>

        <div className="space-y-3">
          <a
            href={`https://www.google.com/maps/search/${encodeURIComponent(signal.place.name + " " + signal.city)}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-sm font-semibold text-clay hover:underline"
          >
            Maps <ArrowUpRight size={14} />
          </a>
          <SignalActions signalId={signal.id} />
        </div>
      </aside>
    </article>
  );
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="text-moss">{icon}</span>
      <span className="truncate">
        <span className="font-semibold text-ink">{value}</span>{" "}
        <span className="text-ink/55">{label}</span>
      </span>
    </div>
  );
}

function labelFor(signalType: string) {
  const labels: Record<string, string> = {
    keyword_spike: "Keyword spike",
    behavior_shift: "Behavior shift",
    sentiment_shift: "Sentiment shift",
    new_place_detected: "New place"
  };

  return labels[signalType] ?? "Local signal";
}
