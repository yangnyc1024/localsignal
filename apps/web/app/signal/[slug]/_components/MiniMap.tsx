import { ArrowUpRight, Navigation } from "lucide-react";
import Link from "next/link";

import type { RelatedSignal, SignalDetail } from "@/lib/types";
import { googleMapsEmbedUrl, googleMapsSearchUrl, nearbyContextLine, shortPlaceName } from "../_utils";

type Props = {
  signal: SignalDetail;
  nearby: RelatedSignal[];
};

export function MiniMap({ signal, nearby }: Props) {
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
