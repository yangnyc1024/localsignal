"use client";

import { MailCheck, Send } from "lucide-react";
import { useState } from "react";

type Status = "idle" | "loading" | "success" | "error";

export function SubscribeForm() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState("");

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("loading");
    setMessage("");

    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

    const response = await fetch(`${baseUrl}/subscribers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email })
    }).catch(() => undefined);

    if (!response?.ok) {
      setStatus("error");
      setMessage("Could not subscribe right now.");
      return;
    }

    setStatus("success");
    setEmail("");
    setMessage("You're on the weekly list.");
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-3">
      <label htmlFor="email" className="flex items-center gap-2 text-sm font-semibold text-ink">
        <MailCheck size={16} />
        Weekly email
      </label>
      <div className="flex gap-2">
        <input
          id="email"
          type="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
          className="min-w-0 flex-1 rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none transition placeholder:text-ink/35 focus:border-moss"
        />
        <button
          type="submit"
          disabled={status === "loading"}
          className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-moss text-white transition hover:bg-ink disabled:cursor-not-allowed disabled:opacity-60"
          aria-label="Subscribe"
          title="Subscribe"
        >
          <Send size={16} />
        </button>
      </div>
      {message ? (
        <p className={status === "success" ? "text-sm text-moss" : "text-sm text-clay"}>
          {message}
        </p>
      ) : null}
    </form>
  );
}
