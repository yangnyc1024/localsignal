import { CheckCircle2, Eye, MinusCircle, Radar } from "lucide-react";

import type { Signal } from "@/lib/types";

type Props = {
  signals: Signal[];
};

type Status = "Moving now" | "Watching" | "Quiet this week";

const channels = [
  { label: "Korean Food", match: matchesKorean },
  { label: "Cafes", match: matchesCafe },
  { label: "Desserts", match: matchesDessert },
  { label: "Late-night", match: matchesLateNight },
  { label: "New Opening", match: matchesOpening }
];

export function CategoryWatch({ signals }: Props) {
  const rows = channels.map((channel) => statusFor(channel.label, signals.filter(channel.match)));

  return (
    <section className="border-y border-line py-5">
      <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-normal text-ink/60">
            <Radar size={17} className="text-moss" />
            Category watch
          </div>
          <p className="mt-1 text-sm leading-6 text-ink/62">A quick scan of what feels active, early, or quiet this week.</p>
        </div>
      </div>
      <div className="grid gap-2 md:grid-cols-5">
        {rows.map((row) => (
          <article key={row.label} className="rounded-lg border border-line bg-white p-4 shadow-sm">
            <div className={`flex items-center gap-2 text-xs font-semibold uppercase tracking-normal ${row.tone}`}>
              {iconFor(row.status)}
              {row.status}
            </div>
            <h2 className="mt-3 text-base font-semibold leading-5 text-ink">{row.label}</h2>
            <p className="mt-2 text-sm leading-5 text-ink/65">{row.detail}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function statusFor(label: string, matched: Signal[]) {
  const strong = matched.filter(isStrongSignal);
  if (strong.length) {
    const top = strongest(strong);
    return {
      label,
      status: "Moving now" as Status,
      detail: `${top.place.name} is the one to notice here right now.`,
      tone: "text-moss"
    };
  }
  if (matched.length) {
    const top = strongest(matched);
    return {
      label,
      status: "Watching" as Status,
      detail: `${top.place.name} has early chatter, but it is not a sure thing yet.`,
      tone: "text-clay"
    };
  }
  return {
    label,
    status: "Quiet this week" as Status,
    detail: "Nothing is standing out yet, which is useful to know too.",
    tone: "text-ink/50"
  };
}

function strongest(signals: Signal[]) {
  return [...signals].sort((left, right) => right.score - left.score)[0];
}

function isStrongSignal(signal: Signal) {
  return signal.signal_strength === "Strong signal";
}

function signalText(signal: Signal) {
  return `${signal.signal_type} ${signal.title} ${signal.summary} ${signal.place.name} ${signal.place.category} ${(signal.evidence.keywords ?? []).join(" ")}`.toLowerCase();
}

function matchesKorean(signal: Signal) {
  const text = signalText(signal);
  return ["korean", "tofu", "bbq", "banchan", "so gong dong", "bcd"].some((term) => text.includes(term));
}

function matchesCafe(signal: Signal) {
  const text = signalText(signal);
  return ["cafe", "coffee", "kuppi", "remote", "wifi", "outlet"].some((term) => text.includes(term));
}

function matchesDessert(signal: Signal) {
  const text = signalText(signal);
  return ["dessert", "bakery", "cake", "pastry", "matcha", "sweet", "cream"].some((term) => text.includes(term));
}

function matchesLateNight(signal: Signal) {
  const text = signalText(signal);
  return ["late night", "late-night", "after 9", "midnight", "night"].some((term) => text.includes(term));
}

function matchesOpening(signal: Signal) {
  const text = signalText(signal);
  return ["opening", "new menu", "soft opening", "new place"].some((term) => text.includes(term));
}

function iconFor(status: Status) {
  if (status === "Moving now") {
    return <CheckCircle2 size={15} />;
  }
  if (status === "Watching") {
    return <Eye size={15} />;
  }
  return <MinusCircle size={15} />;
}
