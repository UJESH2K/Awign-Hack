"use client";

import { Check, CircleSlash, Crosshair, Sparkles, Wand2, X } from "lucide-react";
import { GROUP_LABEL, KIND_LABEL, STATUS, fmt, type Issue, type Segment } from "@/lib/solosim";

type Props = {
  issue: Issue;
  segment?: Segment;
  focused: boolean;
  decided?: string; // action already taken
  clipId: string;
  busy: boolean;
  claudeLeft: number | null;
  onFocus: () => void;
  onDecide: (action: "apply" | "accept" | "reject") => void;
  onClaude?: () => void;
};

function suggestionText(i: Issue): string | null {
  const s = i.suggestion;
  if (!s) return null;
  if (s.field === "start") return `start → ${fmt(Number(s.value))}`;
  if (s.field === "end") return `end → ${fmt(Number(s.value))}`;
  if (s.field === "narration") return `label → “${s.value}”`;
  if (s.field === "add") {
    const v = s.value as { start: number; end: number };
    return `new segment ${fmt(v.start)}–${fmt(v.end)}`;
  }
  return null;
}

/** One nudge for the tester: where, what, the evidence frame with the box, and the one-click fix. */
export function IssueCard({ issue: i, segment, focused, decided, clipId, busy, claudeLeft, onFocus, onDecide, onClaude }: Props) {
  const sug = suggestionText(i);
  const color = i.severity === "fix" ? STATUS.fix.color : STATUS.check.color;
  return (
    <article
      className={`overflow-hidden rounded-xl border bg-surface transition ${focused ? "border-accent shadow-[0_0_0_1px_var(--accent)]" : "border-line"} ${decided ? "opacity-60" : ""}`}
      aria-current={focused}
    >
      <button onClick={onFocus} className="flex w-full gap-3 p-3 text-left">
        <div className="relative w-28 shrink-0 overflow-hidden rounded-md bg-black" style={{ aspectRatio: "16 / 9" }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={`/engine/clips/${clipId}/frame.jpg?t=${i.t.toFixed(2)}&w=320`} alt="" loading="lazy" className="h-full w-full object-cover" />
          {i.box && (
            <span className="absolute border-2 border-[#ff3b55]"
              style={{ left: `${i.box[0] * 100}%`, top: `${i.box[1] * 100}%`, width: `${(i.box[2] - i.box[0]) * 100}%`, height: `${(i.box[3] - i.box[1]) * 100}%` }} />
          )}
          <span className="num absolute bottom-0.5 right-0.5 rounded bg-black/70 px-1 text-[9px] text-white">{fmt(i.t)}</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#0b0b0b]" style={{ background: color }}>
              {KIND_LABEL[i.kind] ?? i.kind}
            </span>
            <span className="text-[10px] uppercase tracking-wide text-muted">{GROUP_LABEL[i.group]}</span>
            {decided && <span className="ml-auto text-[10px] font-semibold uppercase text-clear">{decided}</span>}
          </div>
          <p className="mt-1 text-sm font-medium leading-snug">{i.title}</p>
          {segment && <p className="truncate text-xs text-muted">in “{segment.narration}” · {fmt(segment.start)}–{fmt(segment.end)}</p>}
        </div>
      </button>
      {focused && (
        <div className="border-t border-line px-3 pb-3 pt-2">
          <p className="flex items-start gap-1.5 text-sm text-ink">
            <Crosshair className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
            {i.nudge}
          </p>
          {i.detail && <p className="mt-1 text-xs text-ink-2">{i.detail}</p>}
          {!decided && (
            <div className="mt-3 flex flex-wrap gap-2">
              {sug && (
                <button disabled={busy} onClick={() => onDecide("apply")}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent-fill px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-50">
                  <Wand2 className="h-3.5 w-3.5" /> Apply: {sug}
                </button>
              )}
              <button disabled={busy} onClick={() => onDecide("accept")}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line-strong px-3 py-1.5 text-xs font-medium hover:bg-surface-2 disabled:opacity-50">
                <Check className="h-3.5 w-3.5" /> It&apos;s fine
              </button>
              {i.segment && (
                <button disabled={busy} onClick={() => onDecide("reject")}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-xs text-ink-2 hover:bg-surface-2 hover:text-ink disabled:opacity-50">
                  <X className="h-3.5 w-3.5" /> Drop segment
                </button>
              )}
              {onClaude && i.segment && (
                <button disabled={busy || claudeLeft === null || claudeLeft <= 0} onClick={onClaude}
                  title={claudeLeft === null ? "Claude is not configured" : `Deeper second opinion, about 1 cent ($${claudeLeft.toFixed(2)} left of the cap)`}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-xs text-ink-2 hover:bg-surface-2 hover:text-ink disabled:opacity-40">
                  {claudeLeft === null ? <CircleSlash className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />} Ask Claude
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </article>
  );
}
