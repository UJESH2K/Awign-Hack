"use client";

import { useEffect, useState } from "react";
import { Box, CircleAlert, CircleCheck, CircleX, Loader2 } from "lucide-react";
import { getJSON, postJSON, type RenderResult, type RenderRun, type Segment } from "@/lib/solosim";

const RATE = 0.007; // USD per second, LingBot World 2 (Reactor)
const SECONDS = 30;

function Confirm({ seconds, onYes, onNo }: { seconds: number; onYes: () => void; onNo: () => void }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="spend-h">
      <div className="w-full max-w-sm rounded-2xl border border-line bg-surface p-5 shadow-2xl">
        <h2 id="spend-h" className="text-lg font-semibold">Use paid world-model credit?</h2>
        <p className="mt-2 text-sm text-ink-2">
          LingBot World 2 will render this annotation as a first-person scenario. It costs up to{" "}
          <b className="num text-ink">${(seconds * RATE).toFixed(2)}</b> ({seconds} s cap) of your Reactor credit.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onNo} className="rounded-lg border border-line px-4 py-2 text-sm hover:bg-surface-2">No</button>
          <button onClick={onYes} className="rounded-lg bg-accent-fill px-4 py-2 text-sm font-semibold text-white hover:brightness-110">Yes, spend</button>
        </div>
      </div>
    </div>
  );
}

const VERDICT = {
  works: { icon: CircleCheck, color: "text-clear", label: "Renders as a scenario" },
  partial: { icon: CircleAlert, color: "text-caution", label: "Partly renders" },
  fails: { icon: CircleX, color: "text-collision", label: "Does not render" },
} as const;

/** Side by side: what really happened vs what the world model makes of the annotation. */
export function RenderView({ r }: { r: RenderResult }) {
  const [k, setK] = useState(0);
  const n = r.chunks;
  const realK = Math.round((k / Math.max(1, n - 1)) * (r.real_frames - 1));
  const fails = r.judge.failures ?? [];
  const here = fails.filter((f) => f.k === k);
  const v = VERDICT[(r.judge.verdict as keyof typeof VERDICT) ?? "partial"] ?? VERDICT.partial;
  const m = r.metrics[k];
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <v.icon className={`h-5 w-5 ${v.color}`} aria-hidden />
        <span className={`font-semibold ${v.color}`}>{v.label}</span>
        <span className="text-sm text-ink-2">· {r.judge.summary}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <figure>
          <figcaption className="mb-1 text-xs text-muted">Real footage</figcaption>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={`/engine/renders/${r.id}/real/${realK}.jpg`} alt="Real frame" className="aspect-video w-full rounded-lg bg-black object-cover" />
        </figure>
        <figure>
          <figcaption className="mb-1 truncate text-xs text-muted">LingBot render of “{r.narration}”</figcaption>
          <div className={`relative aspect-video w-full overflow-hidden rounded-lg bg-black ${here.length ? "ring-2 ring-[#ff3b55]" : ""}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/engine/renders/${r.id}/render/${k}.jpg`} alt="Rendered frame" className="h-full w-full object-cover" />
            {m?.hand_boxes.map((b, j) => (
              <span key={j} className="absolute border border-dashed border-[#56d6ff]"
                style={{ left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${(b[2] - b[0]) * 100}%`, height: `${(b[3] - b[1]) * 100}%` }} />
            ))}
            {here.length > 0 && (
              <div className="absolute bottom-2 left-2 right-2 space-y-1">
                {here.map((f, j) => (
                  <span key={j} className="block rounded bg-[#ff3b55] px-2 py-1 text-xs font-semibold text-white">{f.kind}: {f.what}</span>
                ))}
              </div>
            )}
          </div>
        </figure>
      </div>
      <div className="mt-2 flex items-center gap-3">
        <input type="range" min={0} max={n - 1} value={k} onChange={(e) => setK(Number(e.target.value))} className="h-1.5 flex-1 accent-[var(--accent)]" aria-label="Render frame" />
        <span className="num w-40 text-right text-xs text-muted">
          frame {k + 1}/{n} · scene {m ? Math.round(m.scene * 100) : "—"}% · hands {m?.hands ?? "—"}
        </span>
      </div>
      {/* failure strip */}
      <div className="mt-2 flex gap-1" aria-label="Frames with failures">
        {Array.from({ length: n }, (_, i) => {
          const bad = fails.some((f) => f.k === i);
          const drift = (r.metrics[i]?.scene ?? 1) < 0.8;
          return (
            <button key={i} onClick={() => setK(i)} title={bad ? fails.filter((f) => f.k === i).map((f) => f.kind).join(", ") : drift ? "scene drift" : "ok"}
              className={`h-3 flex-1 rounded-sm ${i === k ? "ring-1 ring-ink" : ""}`}
              style={{ background: bad ? "#ff3b55" : drift ? "var(--caution)" : "var(--clear)", opacity: bad || drift ? 1 : 0.5 }} />
          );
        })}
      </div>
      {fails.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm">
          {fails.map((f, j) => (
            <li key={j}>
              <button onClick={() => setK(f.k)} className="text-left hover:underline">
                <b className="text-collision">frame {f.k + 1} · {f.kind}</b> <span className="text-ink-2">{f.what}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[11px] text-muted">Prompt: {r.prompt}</p>
    </div>
  );
}

export function RenderPanel({ clipId, segment }: { clipId: string; segment: Segment }) {
  const [ask, setAsk] = useState(false);
  const [run, setRun] = useState<RenderRun | null>(null);
  const [past, setPast] = useState<{ id: string; segment: string; verdict: string; at: string }[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJSON<{ renders: { id: string; segment: string; verdict: string; at: string }[] }>(`/renders?clip=${clipId}`)
      .then((r) => setPast(r.renders)).catch(() => {});
  }, [clipId, run?.status]);

  useEffect(() => {
    if (!run || run.status === "done" || run.status === "error") return;
    const t = setTimeout(async () => {
      try {
        setRun(await getJSON<RenderRun>(`/renders/${run.id}`));
      } catch {
        /* keep polling */
      }
    }, 1500);
    return () => clearTimeout(t);
  }, [run]);

  const mine = past.filter((p) => p.segment === segment.id);

  async function start() {
    setAsk(false);
    setError(null);
    try {
      setRun(await postJSON<RenderRun>(`/clips/${clipId}/render/${segment.id}`, { confirm_spend: true, seconds: SECONDS }));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="rounded-xl border border-line bg-surface p-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold"><Box className="h-4 w-4 text-accent" /> Will it work as a robot scenario?</h3>
      <p className="mt-1 text-xs text-ink-2">
        LingBot World 2 renders “{segment.narration}” in first person from this segment&apos;s first frame. Where the render
        loses the hands or the object, the annotation is not a usable scenario yet.
      </p>
      {run && run.status !== "done" && run.status !== "error" && (
        <p className="mt-3 flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin text-accent" /> {run.stage}</p>
      )}
      {run?.status === "error" && <p className="mt-3 text-sm text-collision">{run.stage}</p>}
      {error && <p className="mt-3 text-sm text-collision" role="alert">{error}</p>}
      {run?.status === "done" && run.result && <div className="mt-3"><RenderView r={run.result} /></div>}
      {!run && (
        <button onClick={() => setAsk(true)} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-accent-fill px-3 py-2 text-sm font-semibold text-white hover:brightness-110">
          Render in LingBot · up to ${(SECONDS * RATE).toFixed(2)}
        </button>
      )}
      {!run && mine.length > 0 && (
        <div className="mt-3 text-xs text-muted">
          Earlier renders of this segment:{" "}
          {mine.map((p) => (
            <button key={p.id} className="mr-2 text-accent hover:underline"
              onClick={async () => setRun(await getJSON<RenderRun>(`/renders/${p.id}`))}>{p.at.slice(11, 16)} ({p.verdict})</button>
          ))}
        </div>
      )}
      {ask && <Confirm seconds={SECONDS} onYes={start} onNo={() => setAsk(false)} />}
    </section>
  );
}
