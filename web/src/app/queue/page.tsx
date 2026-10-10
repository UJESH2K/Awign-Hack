"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, FileVideo, Loader2, Play, Upload } from "lucide-react";
import { AppHeader } from "@/components/Brand";
import { STATUS, fmt, getJSON, postJSON, type ClipRow } from "@/lib/solosim";

function Bar({ s }: { s: NonNullable<ClipRow["summary"]> }) {
  const n = Math.max(1, s.segments);
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-surface-2" aria-label={`${s.pass} pass, ${s.check} check, ${s.fix} fix`}>
      {(["pass", "check", "fix"] as const).map((k) => (
        <div key={k} style={{ width: `${(100 * s[k]) / n}%`, background: STATUS[k].color }} />
      ))}
    </div>
  );
}

export default function QueuePage() {
  const [rows, setRows] = useState<ClipRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const videoRef = useRef<HTMLInputElement>(null);
  const annRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");

  const load = useCallback(() => getJSON<ClipRow[]>("/clips").then(setRows).catch((e) => setError(e.message)), []);
  useEffect(() => {
    Promise.resolve().then(load);
  }, [load]);
  useEffect(() => {
    if (!rows?.some((r) => r.job?.status === "running")) return;
    const t = setTimeout(load, 1500);
    return () => clearTimeout(t);
  }, [rows, load]);

  async function analyze(id: string) {
    try {
      await postJSON(`/clips/${id}/analyze`);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    const v = videoRef.current?.files?.[0];
    const a = annRef.current?.files?.[0];
    if (!v || !a) return setError("Pick a video and its annotation file.");
    setUploading(true);
    setError(null);
    const fd = new FormData();
    fd.append("video", v);
    fd.append("annotations", a);
    fd.append("title", title || v.name);
    try {
      const r = await fetch("/engine/clips/upload", { method: "POST", body: fd });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail ?? "Upload failed");
      setTitle("");
      if (videoRef.current) videoRef.current.value = "";
      if (annRef.current) annRef.current.value = "";
      await load();
      analyze(body.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
    }
  }

  const done = rows?.filter((r) => r.summary) ?? [];
  const segs = done.reduce((a, r) => a + r.summary!.segments, 0);
  const passed = done.reduce((a, r) => a + r.summary!.pass, 0);
  const hours = (rows ?? []).reduce((a, r) => a + r.duration, 0) / 3600;

  return (
    <div className="sim min-h-screen bg-bg text-ink">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 pb-20 pt-8">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <p className="eyebrow">Before it reaches QA</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">Review queue</h1>
            <p className="mt-2 max-w-2xl text-ink-2">
              Every clip is checked automatically the moment it is annotated. Testers open the clips that need them, start at the
              exact moment that is wrong, and fix it in one click.
            </p>
          </div>
          {done.length > 0 && (
            <dl className="grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-line bg-line text-center">
              {[
                ["Footage", `${(hours * 60).toFixed(1)} min`],
                ["Segments checked", String(segs)],
                ["Auto-passed", `${Math.round((100 * passed) / Math.max(1, segs))}%`],
              ].map(([k, v]) => (
                <div key={k} className="bg-surface px-5 py-3">
                  <dt className="text-[11px] text-muted">{k}</dt>
                  <dd className="num mt-0.5 text-xl font-semibold">{v}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>

        {error && <p className="mt-4 rounded-lg bg-collision/15 px-3 py-2 text-sm" role="alert">{error}</p>}

        <div className="mt-8 grid gap-4 lg:grid-cols-[1fr_320px]">
          <ul className="space-y-3">
            {rows === null && <li className="text-muted">Loading…</li>}
            {rows?.map((r) => {
              const running = r.job?.status === "running";
              return (
                <li key={r.id} className="grid grid-cols-[160px_1fr] gap-4 rounded-xl border border-line bg-surface p-3 sm:grid-cols-[200px_1fr_auto]">
                  <Link href={`/review/${r.id}`} className="relative block overflow-hidden rounded-lg bg-black" style={{ aspectRatio: `${r.width} / ${r.height}` }}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`/engine/clips/${r.id}/frame.jpg?t=${(r.duration / 3).toFixed(1)}&w=400`} alt="" className="h-full w-full object-cover" loading="lazy" />
                    <span className="num absolute bottom-1 right-1 rounded bg-black/70 px-1.5 text-[10px] text-white">{fmt(r.duration)}</span>
                  </Link>
                  <div className="min-w-0">
                    <div className="flex items-baseline gap-2">
                      <Link href={`/review/${r.id}`} className="truncate font-semibold hover:underline">{r.title}</Link>
                      <span className="hidden text-xs text-muted sm:inline">{r.source?.dataset}</span>
                    </div>
                    <p className="text-xs text-muted">{r.segments} annotated segments · {r.task}</p>
                    {r.summary ? (
                      <div className="mt-3 space-y-1.5">
                        <Bar s={r.summary} />
                        <p className="num text-xs text-ink-2">
                          <b className="text-ink">{r.summary.pass}</b> auto-passed · <b className="text-ink">{r.summary.check}</b> to look at ·{" "}
                          <b className="text-ink">{r.summary.fix}</b> to fix · readiness <b className="text-ink">{r.summary.readiness}</b>/100
                          {r.decisions > 0 && <> · {r.decisions} decisions made</>}
                        </p>
                      </div>
                    ) : running ? (
                      <div className="mt-3">
                        <p className="flex items-center gap-2 text-xs"><Loader2 className="h-3.5 w-3.5 animate-spin text-accent" /> {r.job?.stage}</p>
                        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-2"><div className="h-full bg-accent transition-all" style={{ width: `${(r.job?.fraction ?? 0) * 100}%` }} /></div>
                      </div>
                    ) : (
                      <p className="mt-3 text-xs text-muted">Not checked yet.</p>
                    )}
                  </div>
                  <div className="col-span-2 flex items-center gap-2 sm:col-span-1 sm:flex-col sm:items-stretch sm:justify-center">
                    {r.summary ? (
                      <Link href={`/review/${r.id}`} className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent-fill px-3 py-2 text-sm font-semibold text-white hover:brightness-110">
                        Review <ArrowRight className="h-4 w-4" />
                      </Link>
                    ) : (
                      <button onClick={() => analyze(r.id)} disabled={running}
                        className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent-fill px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
                        {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Run the gate
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>

          <form onSubmit={upload} className="h-fit rounded-xl border border-line bg-surface p-4">
            <h2 className="flex items-center gap-2 font-semibold"><Upload className="h-4 w-4 text-accent" /> Add a clip</h2>
            <p className="mt-1 text-xs text-ink-2">A first-person video and its annotations: EPIC-KITCHENS CSV, or JSON rows of {"{start, end, label}"}.</p>
            <label className="mt-3 block text-xs text-muted">Title
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Warehouse picking, worker 12"
                className="mt-1 w-full rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-sm text-ink" />
            </label>
            <label className="mt-3 block text-xs text-muted">Video
              <input ref={videoRef} type="file" accept="video/*" className="mt-1 block w-full text-xs file:mr-2 file:rounded-md file:border-0 file:bg-surface-2 file:px-2 file:py-1 file:text-ink" />
            </label>
            <label className="mt-3 block text-xs text-muted">Annotations
              <input ref={annRef} type="file" accept=".csv,.json" className="mt-1 block w-full text-xs file:mr-2 file:rounded-md file:border-0 file:bg-surface-2 file:px-2 file:py-1 file:text-ink" />
            </label>
            <button disabled={uploading} className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent-fill px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
              {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileVideo className="h-4 w-4" />} Upload and check
            </button>
            <p className="mt-2 text-[11px] text-muted">Runs on this machine; the automatic label check uses a free hosted vision model.</p>
          </form>
        </div>
      </main>
    </div>
  );
}
