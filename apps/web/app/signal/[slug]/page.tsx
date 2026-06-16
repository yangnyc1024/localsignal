import { ArrowLeft, CheckCircle2, Flame, MapPin, Sparkles, TrendingUp } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { getSignalDetail } from "@/lib/api";
import { placeIdentity } from "@/lib/signalStory";
import type { FoodSignal } from "@/lib/types";

import { AboutPlaceSection } from "./_components/AboutPlaceSection";
import { EvidenceSection } from "./_components/EvidenceSection";
import { MiniMap } from "./_components/MiniMap";
import { Section } from "./_components/Section";
import { TrendChart } from "./_components/TrendChart";
import { WhatsMovingSection } from "./_components/WhatsMovingSection";
import {
  curatedEvidence,
  heroFor,
  nearbyPlaces,
  profileCuisine,
  trendPoints,
  whyChanged
} from "./_utils";

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

  const identity = placeIdentity(signal);
  const cuisine = profileCuisine(signal);
  const hero = heroFor(signal);
  const reasons = whyChanged(signal);
  const chart = trendPoints(signal);
  const evidence = curatedEvidence(signal);
  // Split so each snippet appears once: the top voices feature in "What's moving",
  // the rest live under the collapsible "Evidence" receipts.
  const recentVoices = evidence.slice(0, 3);
  const moreEvidence = evidence.slice(3);
  const nearby = nearbyPlaces(signal);
  const foodSignal = signal.evidence.food_signal as FoodSignal | undefined;

  return (
    <main className="min-h-screen">
      <section className="mx-auto grid w-full max-w-[1440px] gap-7 px-4 py-8 md:px-6 md:py-10 lg:px-8 xl:px-10">
        <Link href="/" className="inline-flex w-fit items-center gap-2 text-sm font-semibold text-moss hover:underline">
          <ArrowLeft size={16} />
          Back to this week
        </Link>

        <header className="grid gap-6 border-b border-line pb-8">
          <div className="max-w-4xl">
            <div className="mb-4 flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-normal text-moss">
              <span className="inline-flex items-center gap-1 rounded-md border border-line bg-white/82 px-2.5 py-1">
                <Flame size={13} />
                Signal #{signal.rank}
              </span>
              <span className="rounded-md border border-line bg-white/82 px-2.5 py-1">{signal.signal_strength}</span>
            </div>
            <h1 className="text-4xl font-semibold leading-tight text-ink md:text-6xl">{hero.title}</h1>
            <div className="mt-4 flex flex-wrap items-center gap-2 text-sm font-semibold text-ink/62">
              <span>{identity.area}</span>
              <span className="h-1 w-1 rounded-full bg-ink/25" />
              <span>{cuisine}</span>
              <span className="h-1 w-1 rounded-full bg-ink/25" />
              <span>{signal.date_range || "Recent window"}</span>
            </div>
            <p className="mt-5 max-w-3xl text-lg leading-8 text-ink/76 md:text-xl md:leading-9">{hero.claim}</p>
          </div>
        </header>

        <AboutPlaceSection signal={signal} cuisine={cuisine} />

        <WhatsMovingSection foodSignal={foodSignal} evidence={recentVoices} />

        <Section title="Why This Signal Happened" icon={<Sparkles size={17} />}>
          <div className="grid gap-3">
            {reasons.map((reason) => (
              <div key={reason} className="flex gap-3 rounded-lg border border-line bg-paper p-4 text-sm leading-6 text-ink/76">
                <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-moss" />
                <span>{reason}</span>
              </div>
            ))}
          </div>
        </Section>

        <section className="grid gap-5 lg:grid-cols-[1fr_360px]">
          <Section title="Signal vs Baseline" icon={<TrendingUp size={17} />}>
            <TrendChart points={chart} />
            <p className="mt-4 text-sm leading-6 text-ink/62">
              Weekly mention count this week versus the trailing 30-day average. A gap here is what triggered this signal.
            </p>
          </Section>

          <Section title="Nearby Context" icon={<MapPin size={17} />}>
            <MiniMap signal={signal} nearby={nearby} />
          </Section>
        </section>

        <EvidenceSection evidence={moreEvidence} />
      </section>
    </main>
  );
}
