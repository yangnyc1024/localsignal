import {
  ArrowLeft,
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  CircleDot,
  Info,
  MapPin,
  ShieldCheck,
  Signal as SignalIcon,
  Sparkles,
  TrendingUp
} from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { getSignalDetail } from "@/lib/api";
import { bestReadAs, evidenceNotes, evidenceReceipt, goodFor, phenomenonTitle, placeContext, placeIdentity, readerSummary, watchOut } from "@/lib/signalStory";
import type { SignalDetail } from "@/lib/types";

export const dynamic = "force-dynamic";

type Props = {
  params: Promise<{ slug: string }>;
};

export default async function SignalDetailPage({ params }: Props) {
  const { slug } = await params;
  const signal = await getSignalDetail(slug);

  if (!signal) {
    notFound();
  }

  const notes = evidenceNotes(signal);
  const receiptBase = evidenceReceipt(signal);
  const receipt = receiptBase.some((item) => item.label === "Freshness")
    ? receiptBase
    : [...receiptBase, { label: "Freshness", value: freshnessFor(signal) }];
  const identity = placeIdentity(signal);

  return (
    <main className="min-h-screen">
      <section className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-8 md:px-8 md:py-10">
        <Link href="/" className="inline-flex w-fit items-center gap-2 text-sm font-semibold text-moss hover:underline">
          <ArrowLeft size={16} />
          Back to this week
        </Link>

        <header className="grid gap-5 border-b border-line pb-8 lg:grid-cols-[1fr_300px]">
          <div>
            <div className="mb-4 flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-normal text-moss">
              <span>#{signal.rank}</span>
              <span>{displayStrength(signal)}</span>
              <span>{signal.place.neighborhood ?? signal.city}</span>
            </div>
            <h1 className="max-w-4xl text-3xl font-semibold leading-tight text-ink md:text-5xl">{phenomenonTitle(signal)}</h1>
            <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-ink/68">
              <span className="rounded-md border border-line bg-white/85 px-2.5 py-1 font-semibold text-moss">{identity.cuisine}</span>
              <span className="font-semibold text-ink">{identity.name}</span>
              <span className="inline-flex items-center gap-1 text-ink/58">
                <MapPin size={14} className="text-moss" />
                {identity.area}
              </span>
            </div>
            <p className="mt-5 max-w-3xl text-base leading-7 text-ink/78 md:text-lg">{readerSummary(signal)}</p>
            <div className="mt-5 grid gap-3 md:grid-cols-3">
              <ReaderCue label="Good for" value={goodFor(signal)} />
              <ReaderCue label="Watch out" value={watchOut(signal)} />
              <ReaderCue label="Best read as" value={bestReadAs(signal)} />
            </div>
            <div className="mt-5 flex flex-wrap gap-2">
              {signal.tags.slice(0, 6).map((tag) => (
                <span key={tag} className="rounded-md bg-white/85 px-2.5 py-1 text-xs font-semibold text-ink/70">
                  {tag}
                </span>
              ))}
            </div>
          </div>

          <aside className="rounded-lg border border-line bg-white/88 p-4 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-normal text-ink/50">How to read this</div>
            <div className="mt-3 inline-flex rounded-md border border-line bg-paper px-2.5 py-1 text-xs font-semibold uppercase tracking-normal text-moss">
              {displayStrength(signal)}
            </div>
            <p className="mt-4 text-sm leading-6 text-ink/72">{claimBoundaryFor(signal)}</p>
            <div className="mt-4 grid gap-3 text-sm text-ink/70">
              <HeaderMetric icon={<SignalIcon size={16} />} label={`${identity.cuisine} · ${signal.place.name}`} />
              <HeaderMetric icon={<MapPin size={16} />} label={identity.area} />
              <HeaderMetric icon={<CalendarDays size={16} />} label={signal.date_range} />
            </div>
          </aside>
        </header>

        <section className="grid gap-5 lg:grid-cols-[1fr_320px]">
          <div className="grid gap-5">
            <Panel title="What changed" icon={<TrendingUp size={17} />}>
              <div className="grid gap-3">
                {notes.map((note) => (
                  <div key={note} className="flex gap-3 rounded-lg border border-line bg-paper p-4 text-sm leading-6 text-ink/75">
                    <Sparkles size={16} className="mt-0.5 shrink-0 text-moss" />
                    <span>{note}</span>
                  </div>
                ))}
              </div>
              {signal.what_changed.length ? (
                <div className="mt-4 grid gap-2">
                  {signal.what_changed.slice(0, 4).map((change) => (
                    <p key={change} className="rounded-md bg-white/72 px-3 py-2 text-sm leading-5 text-ink/68">
                      {humanizeChange(change)}
                    </p>
                  ))}
                </div>
              ) : null}
            </Panel>

            <Panel title="Why it might matter" icon={<CheckCircle2 size={17} />}>
              <p className="text-base leading-7 text-ink/80">{signal.why_this_matters || signal.ai_summary}</p>
              <div className="mt-4 rounded-lg border border-line bg-paper p-4">
                <div className="text-xs font-semibold uppercase tracking-normal text-ink/50">What to do with this</div>
                <p className="mt-2 text-sm leading-6 text-ink/75">{actionFrameFor(signal)}</p>
              </div>
            </Panel>

            <Panel title="Evidence receipt" icon={<CircleDot size={17} />}>
              <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                {receipt.map((item) => (
                  <EvidenceStat key={item.label} label={item.label} value={item.value} />
                ))}
              </div>
              <details className="rounded-lg border border-line bg-white/75 p-4">
                <summary className="cursor-pointer text-sm font-semibold text-moss">View supporting excerpts</summary>
                <div className="mt-4 grid gap-3">
                  {signal.evidence_items.length ? (
                    signal.evidence_items.map((item) => (
                      <article key={`${item.platform}-${item.timestamp}-${item.excerpt}`} className="rounded-lg border border-line bg-paper p-4">
                        <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-normal text-moss">
                          <span className="rounded-md bg-white/80 px-2 py-1 text-ink/60">{item.relevance}</span>
                          <span>{item.platform}</span>
                          <span>{formatDateTime(item.timestamp)}</span>
                        </div>
                        <p className="mt-3 text-sm leading-6 text-ink/78">{item.excerpt}</p>
                        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs font-semibold text-ink/55">
                          {item.metadata.region ? <span>Region: {item.metadata.region}</span> : null}
                          {item.source_url ? (
                            <a href={item.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-clay hover:underline">
                              Source <ArrowUpRight size={13} />
                            </a>
                          ) : null}
                        </div>
                      </article>
                    ))
                  ) : (
                    <p className="rounded-lg border border-line bg-paper p-4 text-sm leading-6 text-ink/65">
                      Evidence coverage is still building. This should stay as watching until source excerpts are attached.
                    </p>
                  )}
                </div>
              </details>
            </Panel>

            <Panel title="What we are not claiming" icon={<ShieldCheck size={17} />}>
              <div className="grid gap-2 text-sm leading-6 text-ink/72">
                <p className="rounded-md bg-paper px-3 py-2">This is not a best-restaurant ranking.</p>
                <p className="rounded-md bg-paper px-3 py-2">This does not mean the place matches every person's taste.</p>
                <p className="rounded-md bg-paper px-3 py-2">The claim is limited to observed local activity and retrieved evidence.</p>
              </div>
            </Panel>
          </div>

          <aside className="grid h-fit gap-5">
            <Panel title="Place context" icon={<MapPin size={17} />}>
              <div className="inline-flex rounded-md border border-line bg-paper px-2.5 py-1 text-xs font-semibold uppercase tracking-normal text-moss">{identity.cuisine}</div>
              <div className="mt-3 font-semibold leading-6 text-ink">{signal.place.name}</div>
              <div className="mt-1 text-sm capitalize text-ink/65">{identity.area}</div>
              {signal.place.address ? <div className="mt-2 text-sm leading-5 text-ink/60">{signal.place.address}</div> : null}
              <p className="mt-3 text-sm leading-6 text-ink/72">{placeContext(signal)}</p>
              {signal.place.map_url ? (
                <a href={signal.place.map_url} target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-clay hover:underline">
                  Open map <ArrowUpRight size={14} />
                </a>
              ) : null}
            </Panel>

            <Panel title="Longer-term context" icon={<Info size={17} />}>
              <div className="inline-flex rounded-md border border-line bg-paper px-2.5 py-1 text-xs font-semibold uppercase tracking-normal text-moss">
                {signal.baseline_context.status}
              </div>
              <p className="mt-3 text-sm leading-6 text-ink/75">{signal.baseline_context.summary}</p>
              {signal.baseline_context.delta_vs_baseline ? (
                <p className="mt-3 rounded-md bg-paper px-3 py-2 text-sm leading-5 text-ink/70">
                  {signal.baseline_context.delta_vs_baseline}
                </p>
              ) : null}
              <div className="mt-4 grid grid-cols-3 gap-2 text-center text-xs text-ink/60">
                <BaselineStat label="30d" value={signal.baseline_context.trailing_30d_mentions} />
                <BaselineStat label="90d" value={signal.baseline_context.trailing_90d_mentions} />
                <BaselineStat label="365d" value={signal.baseline_context.trailing_365d_mentions} />
              </div>
            </Panel>

            <Panel title="Evidence confidence" icon={<CircleDot size={17} />}>
              <div className="inline-flex rounded-md border border-line bg-paper px-2.5 py-1 text-xs font-semibold uppercase tracking-normal text-moss">
                {signal.confidence}
              </div>
              <p className="mt-3 text-sm leading-6 text-ink/75">{signal.evidence_assessment}</p>
              <p className="mt-3 text-sm leading-6 text-ink/75">{signal.confidence_reason}</p>
            </Panel>

            <Panel title="Nearby context" icon={<SignalIcon size={17} />}>
              <div className="grid gap-3">
                {signal.related_signals.length ? (
                  signal.related_signals.slice(0, 4).map((related) => (
                    <Link
                      key={related.slug}
                      href={`/signal/${related.slug}`}
                      className="rounded-lg border border-line bg-white/75 p-3 transition hover:-translate-y-0.5 hover:border-moss/60 hover:shadow-sm"
                    >
                      <div className="text-xs font-semibold uppercase tracking-normal text-moss">{labelFor(related.signal_type)}</div>
                      <div className="mt-1 text-sm font-semibold leading-5 text-ink">{related.title}</div>
                      <div className="mt-2 text-xs text-ink/55">{related.place_name} · {related.neighborhood ?? "Nearby"}</div>
                    </Link>
                  ))
                ) : (
                  <p className="text-sm leading-6 text-ink/65">No related local movement is available yet.</p>
                )}
              </div>
            </Panel>
          </aside>
        </section>
      </section>
    </main>
  );
}

function freshnessFor(signal: SignalDetail) {
  if (!signal.evidence_items.length) {
    return "Building";
  }
  const latest = signal.evidence_items
    .map((item) => new Date(item.timestamp).getTime())
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => right - left)[0];
  if (!latest) {
    return signal.date_range;
  }
  const ageDays = Math.max(0, Math.floor((Date.now() - latest) / 86400000));
  if (ageDays === 0) {
    return "Today";
  }
  if (ageDays === 1) {
    return "1 day ago";
  }
  if (ageDays < 14) {
    return `${ageDays} days ago`;
  }
  return formatShortDate(new Date(latest));
}

function formatShortDate(value: Date) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric"
  }).format(value);
}

function ReaderCue({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-white/82 p-3 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-normal text-ink/50">{label}</div>
      <div className="mt-2 text-sm leading-5 text-ink/74">{value}</div>
    </div>
  );
}

function EvidenceStat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-line bg-paper p-3">
      <div className="text-xs font-semibold uppercase tracking-normal text-ink/50">{label}</div>
      <div className="mt-2 text-xl font-semibold text-ink">{value}</div>
    </div>
  );
}

function BaselineStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-paper px-2 py-2">
      <div className="text-base font-semibold text-ink">{value}</div>
      <div>{label}</div>
    </div>
  );
}

function Panel({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-white/88 p-5 shadow-sm">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-normal text-ink/60">
        <span className="text-moss">{icon}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function HeaderMetric({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="shrink-0 text-moss">{icon}</span>
      <span className="truncate">{label}</span>
    </div>
  );
}

function displayStrength(signal: SignalDetail) {
  if (signal.signal_strength === "Strong signal") {
    return "Moving now";
  }
  if (signal.signal_strength === "Watching") {
    return "Worth watching";
  }
  return "Quiet this week";
}

function claimBoundaryFor(signal: SignalDetail) {
  if (signal.signal_strength === "Strong signal") {
    return "Evidence is strong enough to call this movement, not a taste ranking.";
  }
  if (signal.signal_strength === "Watching") {
    return "Early movement only. Useful to watch, not enough to call a breakout.";
  }
  return "No strong claim is being made this week.";
}

function actionFrameFor(signal: SignalDetail) {
  if (signal.signal_strength === "Strong signal") {
    return "Save it if this category matters to you, compare it with nearby movement, and use the map only if the context fits your plans.";
  }
  if (signal.signal_strength === "Watching") {
    return "Keep it on your radar and check back next week for stronger confirmation before treating it as a breakout.";
  }
  return "Use this as a quiet baseline. Nothing here needs action yet.";
}

function humanizeChange(change: string) {
  return change
    .replace(/Mention velocity increased to ([^ ]+) times the baseline level/i, "Mention pace is about $1 above baseline")
    .replace(/Source diversity remains steady with all mentions from/i, "Evidence is still mostly from")
    .replace(/No mentions were observed from outside/i, "No clear outside-area pull from");
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}

function labelFor(signalType: string) {
  const labels: Record<string, string> = {
    keyword_spike: "Menu language",
    behavior_shift: "Behavior shift",
    sentiment_shift: "Tone shift",
    new_place_detected: "New local place",
    review_velocity_spike: "Moving fast"
  };

  return labels[signalType] ?? "Local movement";
}
