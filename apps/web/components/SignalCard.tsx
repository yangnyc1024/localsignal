"use client";

import { Activity, ArrowUpRight, CheckCircle2, Eye, MapPin, ReceiptText, Sparkles, TrendingUp } from "lucide-react";
import { useRouter } from "next/navigation";
import type { KeyboardEvent, MouseEvent, ReactNode } from "react";

import { SignalActions } from "@/components/SignalActions";
import type { Signal } from "@/lib/types";
import { evidenceNotes, evidenceReceipt, goodFor, mentionCountFor, phenomenonTitle, placeIdentity, readerSummary, watchOut } from "@/lib/signalStory";

type Props = {
  signal: Signal;
  rank: number;
};

export function SignalCard({ signal, rank }: Props) {
  const router = useRouter();
  const keywords = signal.evidence.keywords ?? [];
  const notes = evidenceNotes(signal);
  const mapsUrl = `https://www.google.com/maps/search/${encodeURIComponent(signal.place.name + " " + signal.city)}`;
  const detailUrl = `/signal/${signal.slug}`;
  const primaryMetric = primaryMetricFor(signal);
  const identity = placeIdentity(signal);
  const strength = strengthStyle(signal.signal_strength);
  const receipt = evidenceReceipt(signal);

  function openDetail() {
    router.push(detailUrl);
  }

  function handleClick(event: MouseEvent<HTMLElement>) {
    const target = event.target as HTMLElement;
    if (target.closest("a,button")) {
      return;
    }
    openDetail();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openDetail();
    }
  }

  return (
    <article
      role="link"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      className="grid cursor-pointer gap-5 rounded-lg border border-line bg-white p-5 shadow-sm transition duration-200 hover:-translate-y-0.5 hover:border-moss/60 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-moss/30 lg:grid-cols-[minmax(0,1fr)_260px]"
      aria-label={`View signal: ${signal.title}`}
    >
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-normal text-moss">
          <span>#{rank}</span>
          <span>{storyLabelFor(signal)}</span>
          <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 ${strength.badgeClass}`}>
            {strength.icon}
            {displayStrength(signal.signal_strength)}
          </span>
          <span>{signal.place.neighborhood ?? signal.city}</span>
        </div>

        <h2 className="text-xl font-semibold leading-tight text-ink md:text-2xl">{phenomenonTitle(signal)}</h2>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-ink/68">
          <span className="rounded-md border border-line bg-paper px-2.5 py-1 font-semibold text-ink">{identity.cuisine}</span>
          <span className="font-semibold text-ink/82">{identity.name}</span>
          <span className="inline-flex min-w-0 items-center gap-1 text-ink/58">
            <MapPin size={14} className="shrink-0 text-moss" />
            <span className="truncate">{identity.area}</span>
          </span>
        </div>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-ink/78 md:text-base">{readerSummary(signal)}</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <ReaderCue label="Good for" value={goodFor(signal)} />
          <ReaderCue label="Watch out" value={watchOut(signal)} />
        </div>

        <div className="mt-3 grid gap-2">
          {notes.slice(0, 2).map((note) => (
            <div key={note} className="flex gap-2 text-sm leading-5 text-ink/62">
              <Sparkles size={14} className="mt-0.5 shrink-0 text-moss" />
              <span>{note}</span>
            </div>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {keywords.slice(0, 5).map((keyword) => (
            <span key={keyword} className="rounded-md bg-paper px-2.5 py-1 text-xs font-medium text-ink">
              {keyword}
            </span>
          ))}
        </div>

        <div className="mt-5 grid gap-3 text-sm text-ink/70 sm:grid-cols-3">
          <Metric icon={<TrendingUp size={16} />} label={primaryMetric.label} value={primaryMetric.value} />
          <Metric icon={<CheckCircle2 size={16} />} label="confidence" value={signal.confidence} />
          <Metric icon={<Activity size={16} />} label="best read" value={readAsFor(signal)} />
        </div>
      </div>

      <aside className="flex flex-col justify-between gap-4 rounded-md border border-line bg-paper p-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-normal text-ink/50">
            <ReceiptText size={15} className="text-moss" />
            Why it showed up
          </div>
          <div className="mt-3 grid gap-2">
            {receipt.slice(0, 4).map((item) => (
              <div key={item.label} className="flex items-start justify-between gap-3 rounded-md bg-white px-3 py-2 text-sm">
                <span className="text-ink/52">{friendlyReceiptLabel(item.label)}</span>
                <span className="max-w-[140px] text-right font-semibold text-ink">{item.value}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 flex min-w-0 items-start gap-2 text-sm leading-5 text-ink/65">
            <Sparkles size={15} className="mt-0.5 shrink-0 text-moss" />
            <span>{claimBoundaryFor(signal)}</span>
          </div>
        </div>

        <div className="space-y-3">
          <div className="rounded-md border border-line bg-white px-3 py-2">
            <div className="text-xs font-semibold uppercase tracking-normal text-ink/46">Place</div>
            <div className="mt-1 truncate text-sm font-semibold text-ink">{signal.place.name}</div>
            <div className="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-ink/60">
              <MapPin size={13} className="shrink-0 text-moss" />
              <span className="truncate">{identity.area}</span>
            </div>
          </div>
          <a
            href={mapsUrl}
            target="_blank"
            rel="noreferrer"
            onClick={(event) => event.stopPropagation()}
            className="inline-flex items-center gap-1 text-sm font-semibold text-clay hover:underline"
            title="Open map"
          >
            Open map <ArrowUpRight size={14} />
          </a>
          <SignalActions signal={signal} mapsUrl={mapsUrl} />
          <button
            type="button"
            onClick={openDetail}
            className="inline-flex items-center gap-1 text-sm font-semibold text-moss hover:underline"
          >
            Details <ArrowUpRight size={14} />
          </button>
        </div>
      </aside>
    </article>
  );
}

function ReaderCue({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-paper/85 px-3 py-2">
      <div className="text-[11px] font-semibold uppercase tracking-normal text-ink/48">{label}</div>
      <div className="mt-1 text-sm leading-5 text-ink/72">{value}</div>
    </div>
  );
}

function claimBoundaryFor(signal: Signal) {
  if (signal.signal_strength === "Strong signal") {
    return "Enough is repeating to make this worth noticing. It is still not a taste ranking.";
  }
  if (signal.signal_strength === "Watching") {
    return "There is a pattern, but it needs more repeat sightings before we call it a breakout.";
  }
  return "Quiet right now. Nothing here is being forced into a trend.";
}

function displayStrength(strength: Signal["signal_strength"]) {
  if (strength === "Strong signal") {
    return "Moving now";
  }
  if (strength === "Watching") {
    return "Worth watching";
  }
  return "Quiet this week";
}

function readAsFor(signal: Signal) {
  if (signal.signal_strength === "Strong signal") {
    return "Notable";
  }
  if (signal.signal_strength === "Watching") {
    return "Early";
  }
  return "Quiet";
}

function friendlyReceiptLabel(label: string) {
  const labels: Record<string, string> = {
    "Recent mentions": "Recent talk",
    "Source types": "Where it showed up",
    "Repeated terms": "Repeated clue",
    "Evidence read": "How solid",
    Freshness: "Freshness"
  };

  return labels[label] ?? label;
}

function storyLabelFor(signal: Signal) {
  if (signal.signal_strength === "Strong signal") {
    return "What changed";
  }
  if (signal.signal_strength === "Watching") {
    return "Worth watching";
  }
  return "No breakout yet";
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

function primaryMetricFor(signal: Signal) {
  const velocity = signal.evidence.velocity_ratio;
  if (typeof velocity === "number") {
    return { label: "Pace", value: `${velocity.toFixed(1)}x` };
  }

  const mentionCount = mentionCountFor(signal);
  if (mentionCount) {
    return { label: "Mentions", value: mentionCount.toString() };
  }

  return { label: "Momentum", value: labelFor(signal.signal_type) };
}

function labelFor(signalType: string) {
  const labels: Record<string, string> = {
    keyword_spike: "Keyword spike",
    behavior_shift: "Behavior shift",
    sentiment_shift: "Sentiment shift",
    new_place_detected: "New place",
    review_velocity_spike: "Rising fast"
  };

  return labels[signalType] ?? "Food signal";
}

function strengthStyle(strength: Signal["signal_strength"]) {
  if (strength === "Strong signal") {
    return { badgeClass: "bg-moss text-white", icon: <CheckCircle2 size={13} /> };
  }
  if (strength === "Watching") {
    return { badgeClass: "bg-clay/12 text-clay", icon: <Eye size={13} /> };
  }
  return { badgeClass: "bg-ink/8 text-ink/55", icon: <Activity size={13} /> };
}
