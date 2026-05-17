import { Flame, Layers } from "lucide-react";
import Link from "next/link";

import type { AlwaysHotPlace, Signal } from "@/lib/types";

type Props = {
  places: AlwaysHotPlace[];
  signals: Signal[];
};

export function AlwaysHot({ places, signals }: Props) {
  if (!places.length) {
    return null;
  }

  const signalByPlaceId = new Map(signals.map((signal) => [signal.place.id, signal]));

  return (
    <section className="rounded-lg border border-line bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-normal text-ink/60">
            <Flame size={17} className="text-moss" />
            Local Staples
          </h2>
          <p className="mt-2 text-sm leading-6 text-ink/65">
            Places with steady local attention over time. Useful context, not necessarily a new breakout this week.
          </p>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        {places.slice(0, 3).map((place) => {
          const signal = signalByPlaceId.get(place.place_id);
          const content = <AlwaysHotCard place={place} isClickable={Boolean(signal)} />;

          if (!signal) {
            return content;
          }

          return (
            <Link key={place.place_id} href={`/signal/${signal.slug}`} className="group block rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-moss/45">
              {content}
            </Link>
          );
        })}
      </div>
    </section>
  );
}

function AlwaysHotCard({ place, isClickable }: { place: AlwaysHotPlace; isClickable: boolean }) {
  return (
    <article
      key={place.place_id}
      className={`h-full rounded-lg border border-line bg-paper p-4 transition ${
        isClickable ? "cursor-pointer hover:-translate-y-0.5 hover:border-moss/45 hover:bg-white hover:shadow-md" : ""
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-normal text-moss">{place.status}</div>
        <div className="text-sm font-semibold text-ink/55">Steady</div>
      </div>
      <h3 className="mt-2 text-base font-semibold leading-5 text-ink">{place.place_name}</h3>
      <div className="mt-1 text-sm capitalize text-ink/60">
        {place.category} · {place.neighborhood ?? place.city}
      </div>
      <p className="mt-3 line-clamp-3 text-sm leading-5 text-ink/68">{place.summary}</p>
      <div className="mt-3 flex items-center justify-between gap-3 text-xs font-semibold text-ink/55">
        <span className="flex items-center gap-2">
          <Layers size={14} className="text-moss" />
          {place.source_diversity} source type(s) over time
        </span>
        {isClickable ? <span className="text-moss opacity-0 transition group-hover:opacity-100">See current movement →</span> : null}
      </div>
    </article>
  );
}
