import {
  ArrowLeft,
  ArrowUpRight,
  CheckCircle2,
  ChefHat,
  FileText,
  Flame,
  MapPin,
  Navigation,
  Quote,
  Signal as SignalIcon,
  Sparkles,
  TrendingUp
} from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { getSignalDetail } from "@/lib/api";
import { evidenceNotes, placeIdentity } from "@/lib/signalStory";
import type { FoodFact, FoodSignal, RelatedSignal, SignalDetail, SignalEvidenceItem } from "@/lib/types";

export const dynamic = "force-dynamic";

type Props = {
  params: Promise<{ slug: string }>;
};

type SignalRead = {
  summary: string;
  chips: string[];
  items: SignalReadItem[];
  badge: string;
};

type SignalReadItem = {
  label: string;
  read: string;
  detail: string;
};

type RequiredFoodSignal = Required<FoodSignal>;

type ChartPoint = {
  label: string;
  value: number;
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
  const signalRead = signalReadFor(signal);
  const foodSignal = foodSignalFor(signal, signalRead);
  const reasons = whyChanged(signal);
  const chart = trendPoints(signal);
  const evidence = curatedEvidence(signal);
  const nearby = nearbyPlaces(signal);

  return (
    <main className="min-h-screen">
      <section className="grid w-full gap-7 px-4 py-8 md:px-8 md:py-10 lg:px-10 xl:px-14">
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

        {signal.restaurant_brief ? (
          <Section title="Restaurant Brief" icon={<FileText size={17} />}>
            <RestaurantBriefPanel signal={signal} />
          </Section>
        ) : null}

        <Section title="Signal Read" icon={<SignalIcon size={17} />}>
          <SignalReadPanel signal={signal} read={signalRead} foodSignal={foodSignal} />
        </Section>

        <Section title="Food Signal" icon={<Flame size={17} />}>
          <FoodSignalPanel foodSignal={foodSignal} />
        </Section>

        {signal.food_facts && signal.food_facts.length > 0 ? (
          <Section title="Food Intelligence" icon={<ChefHat size={17} />}>
            <FoodFactsPanel facts={signal.food_facts} />
          </Section>
        ) : null}

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
          <Section title="Momentum Over Time" icon={<TrendingUp size={17} />}>
            <TrendChart points={chart} />
            <p className="mt-4 text-sm leading-6 text-ink/62">
              This is a directional read of recent local movement, meant to separate a one-week blip from a more durable pattern.
            </p>
          </Section>

          <Section title="Nearby Context" icon={<MapPin size={17} />}>
            <MiniMap signal={signal} nearby={nearby} />
          </Section>
        </section>

        <EvidenceSection evidence={evidence} />
      </section>
    </main>
  );
}

function Section({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-white/88 p-5 shadow-sm md:p-6">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-normal text-ink/60">
        <span className="text-moss">{icon}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function SignalReadPanel({ signal, read, foodSignal }: { signal: SignalDetail; read: SignalRead; foodSignal: RequiredFoodSignal }) {
  return (
    <div className="grid gap-5">
      <div className="grid gap-4 rounded-lg border border-line bg-paper p-4 md:grid-cols-[1fr_300px] md:p-5">
        <div className="max-w-3xl self-center">
          <p className="text-lg leading-8 text-ink/80">{read.summary}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {read.chips.map((chip) => (
              <span key={chip} className="rounded-md border border-line bg-white/82 px-2.5 py-1 text-xs font-semibold text-moss">
                {chip}
              </span>
            ))}
          </div>
          <div className="mt-4 w-fit rounded-md border border-line bg-white/88 px-3 py-2 text-xs font-semibold uppercase tracking-normal text-ink/56">
            {read.badge}
          </div>
        </div>
        <div className="overflow-hidden rounded-lg border border-line bg-white">
          <img
            src={foodImageUrl(foodSignal, signal)}
            alt={foodSignal.image_alt}
            className="h-56 w-full object-cover md:h-full"
          />
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {read.items.map((item) => (
          <div key={item.label} className="rounded-lg border border-line bg-white/72 p-4">
            <div className="text-xs font-semibold uppercase tracking-normal text-ink/48">{item.label}</div>
            <div className="mt-2 text-base font-semibold leading-6 text-ink">{item.read}</div>
            <p className="mt-2 text-sm leading-6 text-ink/62">{item.detail}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function FoodSignalPanel({ foodSignal }: { foodSignal: RequiredFoodSignal }) {
  const facts = [
    ["Primary pull", foodSignal.primary_pull],
    ["Flavor cue", foodSignal.flavor_cue],
    ["Occasion", foodSignal.occasion],
    ["Confidence", foodSignal.confidence]
  ].filter(([, value]) => value);
  return (
    <div className="grid gap-4">
      <p className="max-w-3xl text-lg leading-8 text-ink/80">{foodSignal.summary}</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {facts.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-line bg-paper p-4">
            <div className="text-xs font-semibold uppercase tracking-normal text-ink/48">{label}</div>
            <div className="mt-2 text-base font-semibold leading-6 text-ink">{value}</div>
          </div>
        ))}
      </div>
      <div className="rounded-lg border border-line bg-paper p-4 text-sm leading-6 text-ink/66">
        {foodSignal.evidence_basis}
      </div>
    </div>
  );
}

function FoodFactsPanel({ facts }: { facts: FoodFact[] }) {
  function dedupeFactsByValue(items: FoodFact[]): FoodFact[] {
    const seen = new Set<string>();
    return items.filter((f) => {
      const key = f.fact_value.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  const byType = {
    dish: dedupeFactsByValue(facts.filter((f) => f.fact_type === "dish")).slice(0, 5),
    occasion: dedupeFactsByValue(facts.filter((f) => f.fact_type === "occasion")).slice(0, 5),
    behavior: dedupeFactsByValue(facts.filter((f) => f.fact_type === "behavior")).slice(0, 5),
  };

  type FactGroup = { key: keyof typeof byType; label: string; items: FoodFact[] };
  const groups: FactGroup[] = ([
    { key: "dish" as const, label: "Dishes", items: byType.dish },
    { key: "occasion" as const, label: "Occasions", items: byType.occasion },
    { key: "behavior" as const, label: "Behaviors", items: byType.behavior },
  ] as FactGroup[]).filter((g) => g.items.length > 0);

  return (
    <div className="grid gap-5">
      <p className="max-w-3xl text-sm leading-6 text-ink/60">
        Structured food intelligence extracted from local evidence — dishes, occasions, and behavioral patterns attached to this place.
      </p>
      <div className={`grid gap-4 ${groups.length >= 3 ? "md:grid-cols-3" : groups.length === 2 ? "md:grid-cols-2" : "md:grid-cols-1"}`}>
        {groups.map((group) => (
          <div key={group.key} className="rounded-lg border border-line bg-paper p-4">
            <div className="mb-3 text-xs font-semibold uppercase tracking-normal text-ink/48">{group.label}</div>
            <ul className="grid gap-3">
              {group.items.map((fact, index) => (
                <li key={`${fact.fact_value}-${index}`} className="border-b border-line/50 pb-3 last:border-0 last:pb-0">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm font-semibold leading-5 text-ink">{fact.fact_value}</span>
                    <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold ${factConfidenceClass(fact.confidence)}`}>
                      {Math.round(fact.confidence * 100)}%
                    </span>
                  </div>
                  {fact.evidence_text ? (
                    <p className="mt-1 text-xs leading-5 text-ink/60">
                      &ldquo;{truncateEvidence(fact.evidence_text, 90)}&rdquo;
                    </p>
                  ) : null}
                  {fact.source_url ? (
                    <a
                      href={fact.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-clay hover:underline"
                    >
                      {fact.source} <ArrowUpRight size={11} />
                    </a>
                  ) : fact.source ? (
                    <span className="mt-1 block text-xs text-ink/42">{fact.source}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function factConfidenceClass(confidence: number) {
  if (confidence >= 0.7) return "bg-moss/12 text-moss";
  if (confidence >= 0.45) return "bg-amber-100 text-amber-700";
  return "bg-ink/6 text-ink/48";
}

function truncateEvidence(value: string, limit: number) {
  const text = cleanText(value);
  if (text.length <= limit) return text;
  const clipped = text.slice(0, limit);
  const lastSpace = clipped.lastIndexOf(" ");
  return (lastSpace > limit * 0.6 ? clipped.slice(0, lastSpace) : clipped) + "…";
}

function RestaurantBriefPanel({ signal }: { signal: SignalDetail }) {
  const brief = signal.restaurant_brief;
  if (!brief) return null;
  return (
    <div className="grid gap-5">
      <div className="rounded-lg border border-line bg-paper p-4 md:p-5">
        <div className="mb-3 inline-flex w-fit rounded-md border border-line bg-white/82 px-2.5 py-1 text-xs font-semibold uppercase tracking-normal text-moss">
          {brief.official_context_note || "Official context, not signal evidence"}
        </div>
        <p className="max-w-4xl text-xl font-semibold leading-8 text-ink md:text-2xl md:leading-9">{brief.what_it_is}</p>
      </div>
      <div className="grid gap-3 lg:grid-cols-[1.3fr_1fr]">
        <div className="rounded-lg border border-line bg-white/72 p-4">
          <div className="text-xs font-semibold uppercase tracking-normal text-ink/48">Signature menu items</div>
          <ul className="mt-3 grid gap-3">
            {brief.signature_menu_items.slice(0, 8).map((item) => (
              <MenuBriefItem key={item} item={item} />
            ))}
          </ul>
        </div>
        <div className="rounded-lg border border-line bg-white/72 p-4">
          <div className="text-xs font-semibold uppercase tracking-normal text-ink/48">Location / format</div>
          <p className="mt-3 text-base leading-7 text-ink/76">{brief.location_format}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-ink/54">
        <span>Sources</span>
        {cleanSourceChips(brief.source_chips).map((source) => (
          <span key={source} className="rounded-full border border-line bg-white/82 px-2.5 py-1">
            {source}
          </span>
        ))}
        <span className="text-ink/42">{brief.trust_note}</span>
      </div>
    </div>
  );
}

function MenuBriefItem({ item }: { item: string }) {
  const [name, ...rest] = item.split(/\s+-\s+/);
  const detail = rest.join(" - ");
  return (
    <li className="text-sm leading-6 text-ink/74">
      <span className="font-semibold text-ink">{cleanText(name)}</span>
      {detail ? <span>: {cleanText(detail)}</span> : null}
    </li>
  );
}

function cleanSourceChips(values: string[]) {
  const labels = values.map((value) => {
    const lower = value.toLowerCase();
    if (lower.includes("google")) return "Google profile";
    if (lower.includes("menu")) return "Menu facts";
    if (lower.includes("official") || lower.includes("website") || lower.startsWith("http")) return "Official website";
    return cleanText(value);
  });
  return unique(labels).slice(0, 4);
}

function TrendChart({ points }: { points: ChartPoint[] }) {
  const width = 560;
  const height = 190;
  const padding = 24;
  const maxValue = Math.max(...points.map((point) => point.value), 100);
  const minValue = Math.min(...points.map((point) => point.value), 0);
  const range = Math.max(1, maxValue - minValue);
  const coords = points.map((point, index) => {
    const x = padding + (index * (width - padding * 2)) / Math.max(1, points.length - 1);
    const y = height - padding - ((point.value - minValue) / range) * (height - padding * 2);
    return { ...point, x, y };
  });
  const path = coords.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
  const area = `${path} L ${coords[coords.length - 1].x} ${height - padding} L ${coords[0].x} ${height - padding} Z`;

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-paper p-4">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-56 w-full" role="img" aria-label="Signal strength over four weeks">
        <path d={area} fill="#4f6b5d" opacity="0.11" />
        <path d={path} fill="none" stroke="#4f6b5d" strokeLinecap="round" strokeLinejoin="round" strokeWidth="4" />
        {coords.map((point) => (
          <g key={point.label}>
            <circle cx={point.x} cy={point.y} r="5" fill="#4f6b5d" />
            <text x={point.x} y={height - 4} textAnchor="middle" className="fill-ink/50 text-[13px] font-semibold">
              {point.label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function MiniMap({ signal, nearby }: { signal: SignalDetail; nearby: RelatedSignal[] }) {
  const places = nearby.slice(0, 3);
  const mapHref = signal.place.map_url || googleMapsSearchUrl(signal);
  const embedHref = googleMapsEmbedUrl(signal);
  return (
    <div>
      <div className="overflow-hidden rounded-lg border border-line bg-paper">
        <iframe
          key={embedHref}
          title={`Map for ${shortPlaceName(signal.place.name)}`}
          src={embedHref}
          className="h-64 w-full border-0"
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
          allowFullScreen
        />
        <div className="grid gap-3 p-4">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 rounded-md bg-moss px-2 py-1 text-xs font-semibold text-white">Focus</div>
            <div className="min-w-0">
              <div className="break-words text-lg font-semibold leading-6 text-ink">{shortPlaceName(signal.place.name)}</div>
              <div className="mt-1 text-sm leading-5 text-ink/60">{signal.place.address || signal.place.neighborhood || signal.city}</div>
            </div>
          </div>
          {places.length ? (
            <div className="grid gap-2 border-t border-line pt-3">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase text-ink/48">
                <Navigation size={13} className="text-moss" />
                Nearby movement
              </div>
              {places.map((place) => (
                <Link key={place.slug} href={`/signal/${place.slug}`} className="grid gap-1 rounded-md bg-white/72 p-3 transition hover:bg-white">
                  <div className="text-sm font-semibold leading-5 text-ink">{shortPlaceName(place.place_name)}</div>
                  <div className="text-xs text-ink/55">{place.neighborhood || "Nearby"} · score {Math.round(place.score)}</div>
                </Link>
              ))}
            </div>
          ) : null}
          <a href={mapHref} target="_blank" rel="noreferrer" className="inline-flex w-fit items-center gap-1 text-sm font-semibold text-clay hover:underline">
            Open in Google Maps <ArrowUpRight size={14} />
          </a>
        </div>
      </div>
      <p className="mt-4 text-sm leading-6 text-ink/70">{nearbyContextLine(signal, nearby)}</p>
    </div>
  );
}

function EvidenceSection({ evidence }: { evidence: SignalEvidenceItem[] }) {
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

function heroFor(signal: SignalDetail) {
  const title = textEvidence(signal, "phenomenon_title") || `${shortPlaceName(signal.place.name)} gaining momentum`;
  const rawClaim = textEvidence(signal, "reader_hook") || signal.ai_summary || signal.summary;
  const claim = isOldSignalPhrase(rawClaim) ? foodSignalClaim(signal) : rawClaim;
  return {
    title: cleanTitle(title, signal),
    claim: cleanText(claim)
  };
}

function signalReadFor(signal: SignalDetail): SignalRead {
  const notes = whyChanged(signal);
  const keywords = cleanKeywords(signal).slice(0, 3);
  const profile = signal.evidence.place_profile;
  const food = signal.evidence.food_signal;
  const identity = placeIdentity(signal);
  const cuisine = profileCuisine(signal);
  const placeSummary = placeProfileSummary(signal);
  const knownFor = usefulProfileText(profile?.known_for)
    ? cleanText(profile?.known_for || "")
    : `${shortPlaceName(signal.place.name)} is a ${cuisine.toLowerCase()} place in ${identity.area}.`;
  const foodPull =
    cleanText(food?.primary_pull || "") ||
    cleanText(profile?.signature_items?.[0] || "") ||
    keywords[0] ||
    cuisine;
  const visitFit =
    cleanText(food?.occasion || "") ||
    cleanText(profile?.occasions?.[0] || "") ||
    occasionFromSignal(signal) ||
    "Local food stop";
  return {
    summary: readSummary(signal, notes, placeSummary),
    chips: signalChips(signal, keywords),
    badge: `${signal.confidence} confidence · ${curatedEvidence(signal).length || "No"} snippets`,
    items: [
      {
        label: "Place profile",
        read: knownFor,
        detail: placeProfileDetail(signal)
      },
      {
        label: "Food pull",
        read: foodPull,
        detail: cleanText(food?.flavor_cue || profile?.flavor_cues?.[0] || "") || "The food read is coming from the place profile and recent evidence."
      },
      {
        label: "Visit fit",
        read: visitFit,
        detail: cleanText(food?.evidence_basis || profile?.caveats || "") || "Useful as a reader-facing occasion, not a ranking against nearby spots."
      }
    ]
  };
}

function foodSignalFor(signal: SignalDetail, read: SignalRead): RequiredFoodSignal {
  const llmFoodSignal = signal.evidence.food_signal;
  const profile = signal.evidence.place_profile;
  const keywords = cleanKeywords(signal);
  const cuisine = displayCuisine(signal, placeIdentity(signal).cuisine);
  const primaryPull =
    cleanText(llmFoodSignal?.primary_pull || "") ||
    cleanText(profile?.signature_items?.[0] || "") ||
    keywords[0] ||
    cuisine;
  const flavorCue =
    cleanText(llmFoodSignal?.flavor_cue || "") ||
    cleanText(profile?.flavor_cues?.[0] || "") ||
    flavorCueFromKeywords(keywords);
  const occasion =
    cleanText(llmFoodSignal?.occasion || "") ||
    cleanText(profile?.occasions?.[0] || "") ||
    occasionFromSignal(signal);
  return {
    summary:
      cleanText(llmFoodSignal?.summary || "") ||
      `${primaryPull} is the clearest food-level read so far. ${read.items[1]?.detail || "The evidence is still being shaped by recent local snippets."}`,
    primary_pull: primaryPull,
    flavor_cue: flavorCue || "Still forming",
    occasion: occasion || "General local interest",
    confidence: cleanText(llmFoodSignal?.confidence || "") || signal.confidence,
    evidence_basis:
      cleanText(llmFoodSignal?.evidence_basis || "") ||
      "Based on retrieved place context, current signal evidence, and repeated food language.",
    image_query:
      cleanText(llmFoodSignal?.image_query || "") ||
      [primaryPull, flavorCue, cuisine].filter(Boolean).join(" "),
    image_alt:
      cleanText(llmFoodSignal?.image_alt || "") ||
      `${primaryPull} food image`
  };
}

function foodImageUrl(foodSignal: RequiredFoodSignal, signal: SignalDetail) {
  const query = (foodSignal.image_query || foodSignal.primary_pull || signal.place.category || "restaurant food").toLowerCase();
  const curated = curatedFoodImage(query);
  if (curated) {
    return curated;
  }
  return `https://source.unsplash.com/900x700/?${encodeURIComponent(query)}`;
}

function curatedFoodImage(query: string) {
  if (/pizza|sourdough/.test(query)) {
    return "https://images.unsplash.com/photo-1513104890138-7c749659a591?auto=format&fit=crop&w=900&q=80";
  }
  if (/coffee|cafe|latte|matcha/.test(query)) {
    return "https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?auto=format&fit=crop&w=900&q=80";
  }
  if (/seafood|crab|shrimp|cajun|boil/.test(query)) {
    return "https://images.unsplash.com/photo-1559737558-2f5a35f4523b?auto=format&fit=crop&w=900&q=80";
  }
  if (/doner|döner|kebab|gyro|shawarma|wrap/.test(query)) {
    return "https://images.unsplash.com/photo-1529006557810-274b9b2fc783?auto=format&fit=crop&w=900&q=80";
  }
  if (/bbq|grill|korean/.test(query)) {
    return "https://images.unsplash.com/photo-1529692236671-f1f6cf9683ba?auto=format&fit=crop&w=900&q=80";
  }
  if (/ramen|sushi|donkatsu|japanese/.test(query)) {
    return "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?auto=format&fit=crop&w=900&q=80";
  }
  return "";
}

function flavorCueFromKeywords(keywords: string[]) {
  if (keywords.some((keyword) => /spicy|heat|hot|cajun|bold/.test(keyword))) return "Heat / bold seasoning";
  if (keywords.some((keyword) => /sweet|dessert|cream|cake|pastry/.test(keyword))) return "Sweet / dessert";
  if (keywords.some((keyword) => /fresh|light|clean/.test(keyword))) return "Fresh / light";
  return "";
}

function occasionFromSignal(signal: SignalDetail) {
  const haystack = [signal.title, signal.summary, signal.ai_summary, ...(signal.evidence.keywords ?? [])].join(" ").toLowerCase();
  if (/late|night/.test(haystack)) return "Late-night visit";
  if (/group|share|party|dinner/.test(haystack)) return "Group dinner";
  if (/brunch|breakfast|coffee|work/.test(haystack)) return "Daytime stop";
  return "";
}

function readSummary(signal: SignalDetail, notes: string[], placeSummary: string) {
  const firstNote = notes[0]?.replace(/\.$/, "");
  if (firstNote) {
    return `${placeSummary} ${firstNote}.`;
  }
  return placeSummary;
}

function placeProfileSummary(signal: SignalDetail) {
  const profile = signal.evidence.place_profile;
  const food = signal.evidence.food_signal;
  const identity = placeIdentity(signal);
  const cuisine = profileCuisine(signal);
  const knownFor = usefulProfileText(profile?.known_for) ? cleanText(profile?.known_for || "") : "";
  const foods = profile?.signature_items?.map(cleanText).filter(usefulProfileText).slice(0, 2) ?? [];
  const occasions = profile?.occasions?.map(cleanText).filter(usefulProfileText).slice(0, 1) ?? [];
  const place = shortPlaceName(signal.place.name);
  if (knownFor && foods.length && occasions.length) {
    const profileSentence = completeProfileSentence(place, knownFor);
    return `${profileSentence} ${formatList(foods)} ${foods.length === 1 ? "is the clearest food pull" : "are the clearest food pulls"} for ${occasions[0].toLowerCase()}.`;
  }
  if (food?.primary_pull || food?.occasion) {
    const pull = cleanText(food.primary_pull || cuisine);
    const cue = cleanText(food.flavor_cue || "");
    const occasion = cleanText(food.occasion || "a local meal");
    const pullPhrase = pull.toLowerCase() === cuisine.toLowerCase() && cue ? cue.toLowerCase() : pull.toLowerCase();
    return `${place} reads as a ${cuisine} place where ${pullPhrase} is the clearest pull for ${occasion.toLowerCase()}.`;
  }
  if (knownFor) {
    return completeProfileSentence(place, knownFor, identity.area);
  }
  return `${place} is the place profile behind this signal, anchored in ${identity.area}.`;
}

function completeProfileSentence(place: string, knownFor: string, area?: string) {
  const cleaned = cleanText(knownFor).replace(/[.。]+$/, "");
  const lower = cleaned.toLowerCase();
  if (lower.startsWith(place.toLowerCase()) || lower.includes(" reads as ")) {
    return `${cleaned}.`;
  }
  return `${place} reads as ${cleaned}${area ? ` in ${area}` : ""}.`;
}

function placeProfileDetail(signal: SignalDetail) {
  const profile = signal.evidence.place_profile;
  const foods = profile?.food_types?.map(cleanText).filter(usefulProfileText).slice(0, 3) ?? [];
  const signatures = profile?.signature_items?.map(cleanText).filter(usefulProfileText).slice(0, 2) ?? [];
  const cues = profile?.flavor_cues?.map(cleanText).filter(usefulProfileText).slice(0, 2) ?? [];
  if (foods.length) {
    return `Profiled around ${formatList(foods)} from retrieved place context.`;
  }
  if (signatures.length || cues.length) {
    return `Profiled around ${formatList([...signatures, ...cues].slice(0, 3))} from retrieved place context.`;
  }
  return "Profile summary comes from retrieved place context plus the evidence attached to this signal.";
}

function profileCuisine(signal: SignalDetail) {
  const identity = placeIdentity(signal);
  const display = displayCuisine(signal, identity.cuisine);
  if (display !== "Local food") {
    return display;
  }
  const foodPull = cleanText(signal.evidence.food_signal?.primary_pull || "");
  if (foodPull) {
    return foodPull;
  }
  return display;
}

function usefulProfileText(value?: string | null): value is string {
  const text = cleanText(value || "").toLowerCase();
  return Boolean(text && text !== "restaurant" && !/tracked as restaurant/.test(text));
}

function signalChips(signal: SignalDetail, keywords: string[]) {
  const chips = [movementChip(signal), evidenceChip(signal)];
  const language = languageRead(keywords);
  if (language.chip) {
    chips.splice(1, 0, language.chip);
  }
  return unique(chips).slice(0, 3);
}

function languageRead(keywords: string[]) {
  if (keywords.some((keyword) => /service|staff|server|attentive/.test(keyword))) {
    return {
      read: "Service is the recurring cue",
      detail: "Recent language points to service experience, not just generic attention.",
      chip: "Service language"
    };
  }
  if (keywords.some((keyword) => /late|night|wait|line|busy/.test(keyword))) {
    return {
      read: "Visit timing is becoming part of the story",
      detail: "The signal is tied to when people go, wait, or talk about the place.",
      chip: "Timing cue"
    };
  }
  if (keywords.some((keyword) => /value|price|ayce|buffet|deal/.test(keyword))) {
    return {
      read: "Value is showing up as a food cue",
      detail: "The repeated language suggests people are reacting to the offer, not only the category.",
      chip: "Value cue"
    };
  }
  return {
    read: "A repeated cue is forming",
    detail: keywords.length ? `The evidence has repeated language around ${formatList(keywords.slice(0, 2))}.` : "The evidence is not yet specific enough to name a repeated demand pattern.",
    chip: keywords.length ? "Repeated language" : ""
  };
}

function movementChip(signal: SignalDetail) {
  if (signal.signal_type === "sentiment_shift") return "Tone shifting";
  if (signal.signal_type === "review_velocity_spike") return "More recent reviews";
  if (signal.signal_type === "keyword_spike") return "Language spike";
  if (signal.signal_type === "new_place_detected") return "New local activity";
  return signal.signal_strength === "Strong signal" ? "Food pull rising" : "Worth watching";
}

function evidenceChip(signal: SignalDetail) {
  const count = curatedEvidence(signal).length;
  if (count >= 3) return "Evidence-backed";
  if (count > 0) return "Early receipts";
  return "Evidence building";
}

function whyChanged(signal: SignalDetail) {
  const llmReasons = evidenceList(signal, "why_changed")
    .concat(evidenceList(signal, "what_changed"))
    .map(humanizeReason)
    .filter(Boolean);
  const changes = signal.what_changed.map(humanizeReason).filter(Boolean);
  const notes = evidenceNotes(signal).map(humanizeReason).filter(Boolean);
  return unique([...llmReasons, ...changes, ...notes]).slice(0, 4);
}

function trendPoints(signal: SignalDetail): ChartPoint[] {
  const current = clamp(Math.round(signal.score), 0, 100);
  const base = clamp(Math.round(signal.baseline_context.heat_score || current * 0.62), 0, 100);
  const midpoint = clamp(Math.round((base + current) / 2), 0, 100);
  const lift = Math.max(5, Math.round((current - base) / 3));
  return [
    { label: "4w", value: clamp(base - lift, 0, 100) },
    { label: "3w", value: base },
    { label: "2w", value: midpoint },
    { label: "Now", value: current }
  ];
}

function curatedEvidence(signal: SignalDetail) {
  return signal.evidence_items
    .filter((item) => item.excerpt.trim())
    .slice(0, 5);
}

function nearbyPlaces(signal: SignalDetail) {
  return signal.related_signals.filter((related) => related.place_name !== signal.place.name).slice(0, 4);
}

function nearbyContextLine(signal: SignalDetail, nearby: RelatedSignal[]) {
  if (!nearby.length) {
    return `${shortPlaceName(signal.place.name)} is the active place in this detail view; nearby context will get richer as more local places attach.`;
  }
  const names = nearby.slice(0, 3).map((place) => shortPlaceName(place.place_name)).join(", ");
  return `${shortPlaceName(signal.place.name)} sits near related local signals including ${names}.`;
}

function textEvidence(signal: SignalDetail, key: string) {
  const value = signal.evidence[key];
  return typeof value === "string" ? cleanText(value) : "";
}

function evidenceList(signal: SignalDetail, key: string) {
  const value = signal.evidence[key];
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string");
  }
  return [];
}

function cleanTitle(value: string, signal: SignalDetail) {
  const title = cleanText(value);
  if (!title || title.includes("|") || isOldSignalPhrase(title)) {
    return `${shortPlaceName(signal.place.name)} gaining momentum`;
  }
  return title;
}

function isOldSignalPhrase(value: string) {
  return /(activity is picking up at|keeps coming up at|tone is shifting at|talk is shifting at|use is changing at)/i.test(value);
}

function foodSignalClaim(signal: SignalDetail) {
  const food = signal.evidence.food_signal;
  const pull = cleanText(food?.primary_pull || profileCuisine(signal));
  const occasion = cleanText(food?.occasion || "a local visit");
  return `${shortPlaceName(signal.place.name)} is showing a food-level read around ${pull.toLowerCase()} for ${occasion.toLowerCase()}.`;
}

function cleanText(value: string) {
  return value
    .replace(/[\u0000-\u001f\u007f-\u009f]/g, " ")
    .replace(/\(\s*(?:[0-9a-fA-F]{2,4}\s*)+\)/g, "")
    .replace(/\b[0-9a-fA-F]{6,}\b/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function cleanKeywords(signal: SignalDetail) {
  const generic = new Set([
    "restaurant",
    "food",
    "place",
    "local",
    "nearby",
    "review",
    "reviews",
    "amazing",
    "great",
    "good",
    "nice",
    "best",
    "really",
    "thanks",
    "thank",
    "yasin",
    "staff",
    "service",
    "recommend",
    "recommended"
  ]);
  return unique([...(signal.evidence.keywords ?? []), ...signal.baseline_context.recurring_keywords])
    .map((keyword) => cleanText(keyword).toLowerCase())
    .filter((keyword) => keyword.length > 3 && !generic.has(keyword))
    .slice(0, 5);
}

function humanizeReason(value: string) {
  return cleanText(value)
    .replace(/Sharp rise in mention volume to about \S+ times the usual rate/i, "Recent mention pace is well above its usual rhythm")
    .replace(/Recent mention pace rose to \S+ (the )?previous baseline/i, "Recent mention pace is well above the previous baseline")
    .replace(/Mention velocity jumped to ([5-9]|\d{2,})x (the )?previous baseline/i, "Recent mention pace is well above the previous baseline")
    .replace(/Mention velocity jumped to ([^ ]+) times previous baseline/i, "Recent mention pace rose to $1x the previous baseline")
    .replace(/Repeated keywords such as 'food', 'service', and 'amazing' appear often/i, "Service language is showing up more often")
    .replace(/Repeated language around food, service, and amazing is showing up more often/i, "Service language is showing up more often")
    .replace(/Repeated keywords such as '([^']+)', '([^']+)', and '([^']+)' appear often/i, "Repeated language around $1, $2, and $3 is showing up more often")
    .replace(/Recent mention pace rose to \S+ (the )?previous baseline/i, "Recent mention pace is well above the previous baseline")
    .replace(/Two independent sources contribute to the signal/i, "The signal is backed by two independent source paths")
    .replace(/Interest extended to at least one area outside the immediate neighborhood/i, "Some demand is coming from outside the immediate neighborhood");
}

function shortPlaceName(value: string) {
  return cleanText(value)
    .replace(/\s*\|.*$/, "")
    .replace(/\s*-\s*Cajun Seafood.*$/i, "")
    .replace(/\s+Nj\b/gi, "")
    .trim();
}

function displayCuisine(signal: SignalDetail, value: string) {
  const lower = value.toLowerCase();
  if (lower && lower !== "restaurant" && lower !== "food") {
    return value;
  }
  const haystack = [
    signal.place.name,
    signal.place.category,
    signal.title,
    signal.summary,
    ...(signal.evidence.keywords ?? [])
  ].join(" ").toLowerCase();
  if (haystack.includes("korean bbq") || haystack.includes("bbq")) return "Korean BBQ";
  if (haystack.includes("korean") || haystack.includes("tofu")) return "Korean food";
  if (haystack.includes("donkatsu") || haystack.includes("ramen") || haystack.includes("sushi")) return "Japanese";
  if (haystack.includes("seafood") || haystack.includes("crab")) return "Seafood";
  if (haystack.includes("cafe") || haystack.includes("coffee")) return "Cafe";
  return "Local food";
}

function unique(values: string[]) {
  return [...new Set(values.filter(Boolean))];
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function formatList(values: string[]) {
  if (values.length <= 1) {
    return values[0] || "recent demand";
  }
  if (values.length === 2) {
    return `${values[0]} and ${values[1]}`;
  }
  return `${values.slice(0, -1).join(", ")}, and ${values[values.length - 1]}`;
}

function googleMapsSearchUrl(signal: SignalDetail) {
  const query = [signal.place.name, signal.place.address, signal.city].filter(Boolean).join(" ");
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

function googleMapsEmbedUrl(signal: SignalDetail) {
  const apiKey = process.env.GOOGLE_PLACES_API_KEY || process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;
  if (apiKey && typeof signal.place.lat === "number" && typeof signal.place.lng === "number") {
    const center = `${signal.place.lat},${signal.place.lng}`;
    return `https://www.google.com/maps/embed/v1/view?key=${encodeURIComponent(apiKey)}&center=${encodeURIComponent(center)}&zoom=15&maptype=roadmap`;
  }
  const query = [shortPlaceName(signal.place.name), signal.place.address, signal.city].filter(Boolean).join(" ");
  return `https://maps.google.com/maps?output=embed&q=${encodeURIComponent(query)}`;
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}
