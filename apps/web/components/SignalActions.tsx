"use client";

import { Bookmark, EyeOff, MousePointerClick, Share2 } from "lucide-react";

type Props = {
  signalId: string;
};

const actions = [
  { event: "click", label: "Open", icon: MousePointerClick },
  { event: "save", label: "Save", icon: Bookmark },
  { event: "share", label: "Share", icon: Share2 },
  { event: "dismiss", label: "Dismiss", icon: EyeOff }
] as const;

export function SignalActions({ signalId }: Props) {
  async function sendFeedback(eventType: string) {
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

    await fetch(`${baseUrl}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        signal_id: signalId,
        event_type: eventType,
        session_id: getSessionId()
      })
    }).catch(() => undefined);
  }

  return (
    <div className="flex flex-wrap gap-2">
      {actions.map(({ event, label, icon: Icon }) => (
        <button
          key={event}
          type="button"
          onClick={() => sendFeedback(event)}
          className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-line bg-white/80 text-ink transition hover:border-moss hover:text-moss"
          aria-label={label}
          title={label}
        >
          <Icon size={16} strokeWidth={2} />
        </button>
      ))}
    </div>
  );
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
