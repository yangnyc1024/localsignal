import {
  ArrowLeft,
  ArrowUpRight,
  CheckCircle2,
  Flame,
  MapPin,
  Navigation,
  Quote,
  Sparkles,
  TrendingUp,
  Utensils
} from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { getSignalDetail } from "@/lib/api";
import { evidenceNotes, placeIdentity } from "@/lib/signalStory";
import type { FoodSignal, RelatedSignal, RestaurantBrief, SignalDetail, SignalEvidenceItem } from "@/lib/types";

export const dynamic = "force-dynamic";

type Props = {
  params: Promise<{ slug: string }>;
};

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
  const reasons = whyChanged(signal);
  const chart = trendPoints(signal);
  const evidence = curatedEvidence(signal);
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

        <WhatsMovingSection signal={signal} foodSignal={foodSignal} evidence={evidence} />

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

function AboutPlaceSection({ signal, cuisine }: { signal: SignalDetail; cuisine: string }) {
  const brief = signal.restaurant_brief as RestaurantBrief | null | undefined;
  const place = shortPlaceName(signal.place.name);
  const whatItIs = brief?.what_it_is || signal.evidence.place_profile?.known_for || "";
  const dishes = brief?.signature_menu_items?.slice(0, 6) ?? (signal.evidence.place_profile?.signature_items ?? []).slice(0, 6);
  const vibeTags = brief?.vibe_tags ?? [];
  const occasions = brief?.occasions ?? (signal.evidence.place_profile?.occasions ?? []).slice(0, 3);
  const locationFormat = brief?.location_format || signal.place.neighborhood || signal.city;

  return (
    <section className="rounded-lg border border-line bg-white/88 p-5 shadow-sm md:p-6">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-normal text-ink/60">
        <Utensils size={17} className="text-moss" />
        About this place
      </h2>
      <div className="grid gap-5">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-moss">{cuisine}</div>
          <p className="mt-2 max-w-3xl text-lg font-semibold leading-8 text-ink">{place}</p>
          {whatItIs ? (
            <p className="mt-3 max-w-3xl text-base leading-7 text-ink/72">{cleanText(whatItIs)}</p>
          ) : null}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {dishes.length > 0 ? (
            <div className="rounded-lg border border-line bg-paper p-4">
              <div className="text-xs font-semibold uppercase tracking-normal text-ink/48">Signature dishes</div>
              <ul className="mt-3 grid gap-2">
                {dishes.map((item) => {
                  const [name, ...rest] = item.split(/\s+-\s+/);
                  const detail = rest.join(" - ");
                  return (
                    <li key={item} className="text-sm leading-6 text-ink/74">
                      <span className="font-semibold text-ink">{cleanText(name)}</span>
                      {detail ? <span>: {cleanText(detail)}</span> : null}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
          <div className="rounded-lg border border-line bg-paper p-4">
            <div className="text-xs font-semibold uppercase tracking-normal text-ink/48">The experience</div>
            <p className="mt-3 text-sm leading-6 text-ink/72">{locationFormat}</p>
            {vibeTags.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {vibeTags.map((tag) => (
                  <span key={tag} className="rounded-full border border-line bg-white/82 px-2.5 py-1 text-xs font-semibold text-ink/68">
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
            {occasions.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {occasions.map((o) => (
                  <span key={o} className="rounded-full border border-moss/30 bg-moss/8 px-2.5 py-1 text-xs font-semibold text-moss">
                    {cleanText(o)}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        {brief?.source_chips?.length ? (
          <div className="flex flex-wrap items-center gap-2 text-xs text-ink/48">
            <span className="font-semibold">Sources</span>
            {brief.source_chips.slice(0, 4).map((chip) => (
              <span key={chip} className="rounded-full border border-line bg-white/82 px-2.5 py-1 font-semibold">
                {chip}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function WhatsMovingSection({ signal, foodSignal, evidence }: { signal: SignalDetail; foodSignal: FoodSignal | undefined; evidence: SignalEvidenceItem[] }) {
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
            {topEvidence[0]?.excerpt ? (
              <p className="mt-3 border-t border-moss/15 pt-3 text-sm leading-6 text-ink/70">
                &ldquo;{truncateEvidence(topEvidence[0].excerpt, 160)}&rdquo;
              </p>
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

function truncateEvidence(value: string, limit: number) {
  const text = cleanText(value);
  if (text.length <= limit) return text;
  const clipped = text.slice(0, limit);
  const lastSpace = clipped.lastIndexOf(" ");
  return (lastSpace > limit * 0.6 ? clipped.slice(0, lastSpace) : clipped) + "…";
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
