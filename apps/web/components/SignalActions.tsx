"use client";

import { Bookmark, EyeOff, MousePointerClick, Share2 } from "lucide-react";
import { useState } from "react";

import type { Signal } from "@/lib/types";

type Props = {
  signal: Signal;
  mapsUrl: string;
};

type ActionEvent = "click" | "save" | "share" | "dismiss";
type ActionStatus = "idle" | "saving" | "saved" | "shared" | "dismissed" | "error";

const actions = [
  { event: "click", label: "Open", icon: MousePointerClick },
  { event: "save", label: "Save", icon: Bookmark },
  { event: "share", label: "Share", icon: Share2 },
  { event: "dismiss", label: "Dismiss", icon: EyeOff }
] as const;

export function SignalActions({ signal, mapsUrl }: Props) {
  const [status, setStatus] = useState<ActionStatus>("idle");

  async function sendFeedback(eventType: ActionEvent) {
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

    const response = await fetch(`${baseUrl}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        signal_id: signal.id,
        event_type: eventType,
        session_id: getSessionId()
      })
    }).catch(() => undefined);

    return response?.ok ?? false;
  }

  async function handleAction(eventType: ActionEvent) {
    setStatus("saving");

    if (eventType === "click") {
      window.open(mapsUrl, "_blank", "noopener,noreferrer");
    }

    if (eventType === "share") {
      await shareSignal(signal, mapsUrl);
    }

    const saved = await sendFeedback(eventType);
    if (!saved) {
      setStatus("error");
      return;
    }

    if (eventType === "save") {
      setStatus("saved");
      return;
    }

    if (eventType === "share") {
      setStatus("shared");
      return;
    }

    if (eventType === "dismiss") {
      setStatus("dismissed");
      return;
    }

    setStatus("idle");
  }

  return (
    <div onClick={(event) => event.stopPropagation()}>
      <div className="flex flex-wrap gap-2">
        {actions.map(({ event, label, icon: Icon }) => (
          <button
            key={event}
            type="button"
            onClick={() => handleAction(event)}
            disabled={status === "saving"}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-line bg-white/80 text-ink transition hover:border-moss hover:text-moss disabled:cursor-not-allowed disabled:opacity-55"
            aria-label={label}
            title={tooltipFor(event)}
          >
            <Icon size={16} strokeWidth={2} />
          </button>
        ))}
      </div>
      {statusMessage(status) ? <p className="mt-2 text-xs font-medium text-moss">{statusMessage(status)}</p> : null}
    </div>
  );
}

function tooltipFor(eventType: ActionEvent) {
  const labels: Record<ActionEvent, string> = {
    click: "Open map",
    save: "Save signal",
    share: "Share signal",
    dismiss: "Hide signal"
  };

  return labels[eventType];
}

async function shareSignal(signal: Signal, mapsUrl: string) {
  const text = `${signal.title}\n${signal.summary}\n${mapsUrl}`;

  if (navigator.share) {
    await navigator.share({
      title: signal.title,
      text,
      url: mapsUrl
    }).catch(() => undefined);
    return;
  }

  await navigator.clipboard?.writeText(text).catch(() => undefined);
}

function statusMessage(status: ActionStatus) {
  const messages: Record<ActionStatus, string> = {
    idle: "",
    saving: "Saving...",
    saved: "Saved",
    shared: "Copied",
    dismissed: "Dismissed",
    error: "Could not save"
  };

  return messages[status];
}

function getSessionId() {
  const key = "localsignal_session_id";
  const existing = window.localStorage.getItem(key);
  if (existing) {
    return existing;
  }

  const value = window.crypto.randomUUID();
  window.localStorage.setItem(key, value);
  return value;
}
