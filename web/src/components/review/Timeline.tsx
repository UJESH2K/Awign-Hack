"use client";

import { useMemo, useRef, useState } from "react";
import { ZoomIn, ZoomOut } from "lucide-react";
import { STATUS, fmt, type Issue, type Segment, type Track } from "@/lib/solosim";

type Props = {
  duration: number;
  segments: Segment[];
  status: Record<string, "pass" | "check" | "fix">;
  issues: Issue[];
  track: Track | null;
  time: number;
  selected: string | null;
  focus: string | null;
  onSeek: (t: number) => void;
  onSelect: (id: string) => void;
  onFocus: (issue: Issue) => void;
};

const ROW = 24;

/** Greedy lane packing: overlapping segments go to separate rows, so overlaps are visible. */
function lanes(segs: Segment[]) {
  const ends: number[] = [];
  const out: Record<string, number> = {};
  for (const s of [...segs].sort((a, b) => a.start - b.start)) {
    let r = ends.findIndex((e) => e <= s.start + 0.05);
    if (r < 0) {
      r = ends.length;
      ends.push(0);
    }
    ends[r] = s.end;
    out[s.id] = r;
  }
  return { rows: Math.max(1, ends.length), lane: out };
}

export function Timeline({ duration, segments, status, issues, track, time, selected, focus, onSeek, onSelect, onFocus }: Props) {
  const [zoom, setZoom] = useState(1);
  const box = useRef<HTMLDivElement>(null);
  const { rows, lane } = useMemo(() => lanes(segments), [segments]);
  const pct = (t: number) => `${(100 * t) / Math.max(0.001, duration)}%`;
  const ticks = useMemo(() => {
    const step = duration > 240 ? 30 : duration > 90 ? 10 : 5;
    return Array.from({ length: Math.floor(duration / step) + 1 }, (_, i) => i * step);
  }, [duration]);
  const act = useMemo(() => {
    if (!track || !track.t.length) return null;
    const hi = Math.max(...track.activity, 1e-6);
    const pts = track.t.map((t, i) => `${(1000 * t) / duration},${30 - (28 * track.activity[i]) / hi}`).join(" ");
    const blurred: [number, number][] = [];
    let s: number | null = null;
    track.t.forEach((t, i) => {
      const b = track.blur[i] < track.blur_min;
      if (b && s === null) s = t;
      if (!b && s !== null) {
        if (t - s > 0.3) blurred.push([s, t]);
        s = null;
      }
    });
    return { pts, blurred };
  }, [track, duration]);

  const seekFromEvent = (e: React.MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    onSeek(((e.clientX - r.left) / r.width) * duration);
  };

  return (
    <div className="rounded-xl border border-line bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
          {(["pass", "check", "fix"] as const).map((k) => (
            <span key={k} className="inline-flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-sm" style={{ background: STATUS[k].color }} />{STATUS[k].label}</span>
          ))}
          <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-sm bg-[#56d6ff]/40" />hand activity</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-sm bg-collision/40" />blurred</span>
        </div>
        <div className="flex items-center gap-1">
          <button className="ctl h-7 w-7" onClick={() => setZoom((z) => Math.max(1, z / 2))} aria-label="Zoom out" disabled={zoom === 1}><ZoomOut className="h-3.5 w-3.5" /></button>
          <span className="num w-8 text-center text-[11px] text-muted">{zoom}×</span>
          <button className="ctl h-7 w-7" onClick={() => setZoom((z) => Math.min(16, z * 2))} aria-label="Zoom in"><ZoomIn className="h-3.5 w-3.5" /></button>
        </div>
      </div>
      <div ref={box} className="overflow-x-auto">
        <div className="relative select-none px-3 pb-2 pt-1" style={{ width: `${100 * zoom}%`, minWidth: "100%" }}>
          {/* time axis */}
          <div className="relative h-5 cursor-pointer" onClick={seekFromEvent}>
            {ticks.map((t) => (
              <span key={t} className="num absolute top-0.5 -translate-x-1/2 text-[10px] text-muted" style={{ left: pct(t) }}>{fmt(t).replace(/\.0$/, "")}</span>
            ))}
          </div>
          {/* issues */}
          <div className="relative h-6" aria-label="Issues">
            {issues.map((i) => (
              <button key={i.id} onClick={() => onFocus(i)} title={`${i.title} (${fmt(i.t)})`}
                className={`absolute top-1 h-4 -translate-x-1/2 rounded-sm transition ${focus === i.id ? "ring-2 ring-ink" : ""}`}
                style={{ left: pct(i.t), width: i.t_end ? `max(8px, ${(100 * (i.t_end - i.t)) / duration}%)` : 8,
                  transform: i.t_end ? "none" : undefined,
                  background: i.severity === "fix" ? STATUS.fix.color : STATUS.check.color, opacity: focus && focus !== i.id ? 0.55 : 1 }} />
            ))}
          </div>
          {/* segments */}
          <div className="relative cursor-pointer" style={{ height: rows * ROW + 4 }} onClick={seekFromEvent}>
            {segments.map((s) => {
              const st = status[s.id] ?? "pass";
              const sel = selected === s.id;
              return (
                <button key={s.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelect(s.id);
                    onSeek(s.start);
                  }}
                  title={`${s.narration} · ${fmt(s.start)}–${fmt(s.end)}`}
                  className={`absolute overflow-hidden whitespace-nowrap rounded px-1 text-left text-[10px] font-medium leading-[20px] text-[#0b0b0b] transition ${sel ? "ring-2 ring-ink" : "hover:brightness-110"}`}
                  style={{ left: pct(s.start), width: `max(3px, ${(100 * (s.end - s.start)) / duration}%)`, top: 2 + lane[s.id] * ROW, height: ROW - 4,
                    background: STATUS[st].color, opacity: st === "pass" ? 0.75 : 1 }}>
                  {s.narration}
                </button>
              );
            })}
          </div>
          {/* activity + blur */}
          {act && (
            <svg viewBox="0 0 1000 32" preserveAspectRatio="none" className="mt-1 h-8 w-full cursor-pointer" onClick={seekFromEvent} aria-hidden>
              {act.blurred.map(([a, b]) => (
                <rect key={a} x={(1000 * a) / duration} y="0" width={(1000 * (b - a)) / duration} height="32" fill="var(--collision)" opacity="0.3" />
              ))}
              <polyline points={act.pts} fill="none" stroke="#56d6ff" strokeWidth="1.2" vectorEffect="non-scaling-stroke" opacity="0.9" />
            </svg>
          )}
          {/* playhead */}
          <div className="pointer-events-none absolute bottom-0 top-0 w-px bg-ink" style={{ left: `calc(0.75rem + (100% - 1.5rem) * ${time / Math.max(0.001, duration)})` }} />
        </div>
      </div>
    </div>
  );
}
