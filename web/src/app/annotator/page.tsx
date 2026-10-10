"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, CheckCircle2, FileSpreadsheet, FileVideo, Loader2, Play, Send, Upload, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { AppHeader } from "@/components/Brand";
import { Count, Item, Ring, Stagger } from "@/components/Motion";
import { ENGINE_URL, STATUS, fmt, getJSON, postJSON, type ClipRow, type Workflow } from "@/lib/solosim";

type Row = ClipRow & { workflow: Workflow };

function Bar({ s }: { s: NonNullable<ClipRow["summary"]> }) {
  const n = Math.max(1, s.segments);
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-surface-2">
      {(["pass", "check", "fix"] as const).map((k) => (
        <div key={k} className="transition-all duration-500" style={{ width: `${(100 * s[k]) / n}%`, background: STATUS[k].color }} />
      ))}
    </div>
  );
}

const WF_BADGE: Record<string, { label: string; cls: string }> = {
  draft: { label: "Draft", cls: "bg-surface-2 text-muted" },
  submitted: { label: "Submitted to QA", cls: "bg-accent-soft text-accent" },
  returned: { label: "Returned by QA", cls: "bg-warning/15 text-warning" },
  approved: { label: "Approved", cls: "bg-clear/15 text-clear" },
};

export default function AnnotatorPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [name, setName] = useState("");
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    try { const n = localStorage.getItem("solosim_annotator"); if (n) setName(n); } catch {}
  }, []);
  const videoRef = useRef<HTMLInputElement>(null);
  const annRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [picked, setPicked] = useState<{ video?: File; ann?: File }>({});
  const [over, setOver] = useState(false);

  const load = useCallback(() => getJSON<Row[]>("/clips").then(setRows).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!rows?.some((r) => r.job?.status === "running")) return;
    const t = setTimeout(load, 1200);
    return () => clearTimeout(t);
  }, [rows, load]);

  async function analyze(id: string) {
    try { await postJSON(`/clips/${id}/analyze`); load(); } catch (e) { setError((e as Error).message); }
  }

  async function submit(id: string, open: number) {
    if (open > 0 && !confirm(`${open} segment${open > 1 ? "s are" : " is"} still flagged. QA will see them. Submit anyway?`)) return;
    try { localStorage.setItem("solosim_annotator", name); } catch {}
    try {
      await postJSON(`/clips/${id}/workflow`, { action: "submit", annotator: name });
      load();
    } catch (e) { setError((e as Error).message); }
  }

  /** One drop handles both files: whatever looks like video is the clip, the rest is the annotation. */
  function take(files: FileList | File[]) {
    const next = { ...picked };
    for (const f of Array.from(files)) {
      if (f.type.startsWith("video/") || /\.(mp4|mov|mkv|webm|avi)$/i.test(f.name)) next.video = f;
      else if (/\.(csv|json)$/i.test(f.name)) next.ann = f;
    }
    setPicked(next);
    setError(null);
  }

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    const v = picked.video ?? videoRef.current?.files?.[0];
    const a = picked.ann ?? annRef.current?.files?.[0];
    if (!v) return setError("Pick a first-person video.");
    if (!name.trim()) return setError("Enter your name first.");
    try { localStorage.setItem("solosim_annotator", name); } catch {}
    setUploading(true); setError(null);
    const fd = new FormData();
    fd.append("video", v);
    if (a) fd.append("annotations", a);
    fd.append("title", title || v.name.replace(/\.[^.]+$/, ""));
    fd.append("annotator", name);
    try {
      // Straight to the engine: the Next proxy truncates request bodies over 10MB.
      const r = await fetch(`${ENGINE_URL}/clips/upload`, { method: "POST", body: fd });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail ?? "Upload failed");
      setTitle("");
      setPicked({});
      if (videoRef.current) videoRef.current.value = "";
      if (annRef.current) annRef.current.value = "";
      await load();
      analyze(body.id);
    } catch (err) { setError((err as Error).message); } finally { setUploading(false); }
  }

  return (
    <div className="sim min-h-screen bg-bg text-ink">
      <AppHeader />
      <main className="mx-auto max-w-[1600px] px-4 pb-24 pt-8 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <p className="eyebrow">Annotator desk</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Your annotations</h1>
            <p className="mt-2 max-w-2xl text-ink-2">
              Drop a clip with its annotations. SoloSim checks every segment against the footage while you watch, pinpoints the
              mistakes, and lets you fix them before QA sees anything. You can submit without reviewing — QA will just see the full report.
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted">Your name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Ravi"
              className="w-44 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-ink shadow-[var(--shadow-1)]" />
          </label>
        </div>

        <AnimatePresence>
          {error && (
            <motion.p initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className="mt-4 flex items-center justify-between gap-3 rounded-lg border border-collision/30 bg-collision/10 px-3 py-2 text-sm" role="alert">
              {error}
              <button onClick={() => setError(null)} className="text-muted hover:text-ink"><X className="h-4 w-4" /></button>
            </motion.p>
          )}
        </AnimatePresence>

        <div className="mt-8 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]">
          <Stagger className="space-y-3">
            {rows === null && <li className="list-none text-muted">Loading…</li>}
            {rows?.length === 0 && (
              <Item className="card grid place-items-center gap-1 p-10 text-center">
                <FileVideo className="h-7 w-7 text-muted" />
                <p className="mt-1 font-medium">No clips yet</p>
                <p className="text-sm text-muted">Drop a video and its CSV on the right to run the gate.</p>
              </Item>
            )}
            {rows?.map((r) => {
              const running = r.job?.status === "running";
              const wf = r.workflow;
              const badge = WF_BADGE[wf?.status ?? "draft"] ?? WF_BADGE.draft;
              const returned = wf?.status === "returned";
              const lastReturn = returned ? [...(wf?.history ?? [])].reverse().find((h) => h.action === "return") : null;
              return (
                <Item key={r.id}>
                  <div className={`card card-lift p-3 ${returned ? "border-warning/40 bg-warning/[0.04]" : ""}`}>
                    <div className="grid grid-cols-[132px_1fr] gap-4 sm:grid-cols-[200px_1fr_auto]">
                      <Link href={`/review/${r.id}?role=annotator`} className="stage relative block overflow-hidden rounded-xl" style={{ aspectRatio: `${r.width} / ${r.height}` }}>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={`/engine/clips/${r.id}/frame.jpg?t=${(r.duration / 3).toFixed(1)}&w=400`} alt="" className="h-full w-full object-cover" loading="lazy" />
                        <span className="num absolute bottom-1 right-1 rounded bg-black/70 px-1.5 text-[10px] text-white">{fmt(r.duration)}</span>
                      </Link>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-baseline gap-2">
                          <Link href={`/review/${r.id}?role=annotator`} className="truncate font-semibold hover:underline">{r.title}</Link>
                          <span className={`pill ${badge.cls}`}>{badge.label}</span>
                          {(wf?.version ?? 0) > 1 && <span className="num pill bg-surface-2 text-muted">v{wf.version}</span>}
                        </div>
                        <p className="text-xs text-muted">{r.segments} segments · {r.source?.dataset}</p>
                        {running ? (
                          <div className="mt-2 flex items-center gap-3">
                            <Ring value={r.job?.fraction ?? 0} />
                            <div className="min-w-0 flex-1">
                              <p className="truncate text-xs font-medium">{r.job?.stage}</p>
                              <div className="relative mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-2 sweep">
                                <div className="h-full rounded-full bg-accent transition-all duration-500" style={{ width: `${(r.job?.fraction ?? 0) * 100}%` }} />
                              </div>
                              {r.summary && (
                                <p className="num mt-1.5 text-[11px] text-ink-2">
                                  so far: <b className="text-ink">{r.summary.fix}</b> to fix · <b className="text-ink">{r.summary.check}</b> to review
                                </p>
                              )}
                            </div>
                          </div>
                        ) : r.summary ? (
                          <div className="mt-2 space-y-1.5">
                            <Bar s={r.summary} />
                            <p className="num text-xs text-ink-2">
                              <b className="text-ink"><Count to={r.summary.fix} duration={0.6} /></b> to fix ·{" "}
                              <b className="text-ink"><Count to={r.summary.check} duration={0.6} /></b> to review · readiness{" "}
                              <b className="text-ink"><Count to={r.summary.readiness} /></b>/100
                            </p>
                            {r.timing && r.timing.seconds > 0 && (
                              <p className="num text-[11px] font-medium text-accent">
                                Analysed in {r.timing.seconds.toFixed(1)}s{r.timing.realtime_factor ? ` · ${r.timing.realtime_factor.toFixed(1)}× realtime` : ""}
                              </p>
                            )}
                          </div>
                        ) : (
                          <p className="mt-2 text-xs text-muted">Not checked yet.</p>
                        )}
                      </div>
                      <div className="col-span-2 flex items-center gap-2 sm:col-span-1 sm:flex-col sm:items-stretch sm:justify-center">
                        {r.summary && !running ? (
                          <>
                            <Link href={`/review/${r.id}?role=annotator`} className="btn btn-quiet">
                              Review <ArrowRight className="h-4 w-4" />
                            </Link>
                            {(wf?.status === "draft" || wf?.status === "returned") && (
                              <button onClick={() => submit(r.id, r.summary?.fix ?? 0)} className="btn btn-primary">
                                <Send className="h-4 w-4" /> {wf?.status === "returned" ? "Resubmit" : "Submit to QA"}
                              </button>
                            )}
                            {wf?.status === "approved" && (
                              <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-clear"><CheckCircle2 className="h-4 w-4" /> Approved</span>
                            )}
                          </>
                        ) : (
                          <button onClick={() => analyze(r.id)} disabled={running} className="btn btn-primary">
                            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} {running ? "Analysing…" : "Analyse"}
                          </button>
                        )}
                      </div>
                    </div>
                    {returned && lastReturn?.note && (
                      <div className="mt-3 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm">
                        <span className="font-semibold text-warning">QA returned this:</span> {lastReturn.note}
                      </div>
                    )}
                  </div>
                </Item>
              );
            })}
          </Stagger>

          <form onSubmit={upload} className="card h-fit p-4 lg:sticky lg:top-[4.5rem]">
            <h2 className="flex items-center gap-2 font-semibold"><Upload className="h-4 w-4 text-accent" /> New submission</h2>
            <p className="mt-1 text-xs text-ink-2">Your first-person video and its annotation CSV or JSON. The gate starts the moment the upload lands.</p>

            <div
              onDragOver={(e) => { e.preventDefault(); setOver(true); }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files); }}
              onClick={() => videoRef.current?.click()}
              className={`mt-3 grid cursor-pointer place-items-center gap-1 rounded-xl border-2 border-dashed px-4 py-7 text-center transition ${over ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong hover:bg-surface-2"}`}
            >
              <Upload className={`h-6 w-6 ${over ? "text-accent" : "text-muted"}`} />
              <p className="text-sm font-medium">Drop the clip and the CSV here</p>
              <p className="text-xs text-muted">or click to pick the video</p>
            </div>

            <div className="mt-3 space-y-1.5 text-xs">
              {picked.video && (
                <p className="flex items-center gap-2 rounded-lg bg-surface-2 px-2.5 py-1.5">
                  <FileVideo className="h-3.5 w-3.5 shrink-0 text-accent" />
                  <span className="truncate">{picked.video.name}</span>
                  <span className="num ml-auto shrink-0 text-muted">{(picked.video.size / 1e6).toFixed(1)} MB</span>
                </p>
              )}
              {picked.ann ? (
                <p className="flex items-center gap-2 rounded-lg bg-surface-2 px-2.5 py-1.5">
                  <FileSpreadsheet className="h-3.5 w-3.5 shrink-0 text-accent" />
                  <span className="truncate">{picked.ann.name}</span>
                </p>
              ) : (
                <button type="button" onClick={() => annRef.current?.click()} className="text-accent hover:underline">+ add the annotation file</button>
              )}
            </div>

            <input ref={videoRef} type="file" accept="video/*" className="hidden" onChange={(e) => e.target.files && take(e.target.files)} />
            <input ref={annRef} type="file" accept=".csv,.json" className="hidden" onChange={(e) => e.target.files && take(e.target.files)} />

            <label className="mt-3 block text-xs text-muted">Title (optional)
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Kitchen task batch 12"
                className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-sm text-ink" />
            </label>

            <button disabled={uploading || !name.trim() || !picked.video} className="btn btn-primary mt-4 w-full py-2.5">
              {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Upload and analyse
            </button>
            {!name.trim() && <p className="mt-2 text-center text-[11px] text-muted">Add your name above so QA knows whose work this is.</p>}
          </form>
        </div>
      </main>
    </div>
  );
}
