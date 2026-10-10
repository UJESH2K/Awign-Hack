"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Loader2, Play, RotateCcw, ShieldCheck, UserRound, Wand2 } from "lucide-react";
import { AppHeader } from "@/components/Brand";
import { Count, Item, Reveal, Stagger } from "@/components/Motion";
import { KIND_LABEL, STATUS, fmt, getJSON, postJSON, type AnnotatorReport, type ClipRow, type QAReport, type Workflow } from "@/lib/solosim";

type Row = ClipRow & { workflow: Workflow };

function MistakeReport({ a }: { a: AnnotatorReport }) {
  const kinds = Object.entries(a.by_kind).sort((x, y) => y[1] - x[1]);
  const max = Math.max(1, ...kinds.map(([, n]) => n));
  const [showAll, setShowAll] = useState(false);
  const list = showAll ? a.mistakes : a.mistakes.slice(0, 8);
  return (
    <li className="card p-4">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h3 className="flex items-center gap-2 font-semibold"><UserRound className="h-4 w-4 text-accent" /> {a.annotator}</h3>
        <span className="num text-xs text-ink-2">{a.clips} clip{a.clips > 1 ? "s" : ""} · {a.segments} segments · {fmt(a.footage_s)} of footage</span>
        <span className="num text-xs"><b className="text-collision">{a.issues}</b> open mistakes · <b>{a.per_minute}</b> per minute of footage</span>
        {a.fixed_before_submit > 0 && <span className="num text-xs text-clear">fixed {a.fixed_before_submit} before submitting</span>}
      </div>
      <div className="mt-3 grid gap-4 md:grid-cols-[260px_1fr]">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted">How often</p>
          <ul className="mt-1.5 space-y-1">
            {kinds.map(([k, n]) => (
              <li key={k} className="grid grid-cols-[110px_1fr_24px] items-center gap-2 text-xs">
                <span className="truncate">{KIND_LABEL[k] ?? k}</span>
                <span className="h-1.5 overflow-hidden rounded-full bg-surface-2"><span className="block h-full bg-collision/80" style={{ width: `${(100 * n) / max}%` }} /></span>
                <span className="num text-right text-ink-2">{n}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-wide text-muted">Where (click to jump to the exact second)</p>
          <ul className="mt-1.5 divide-y divide-line text-xs">
            {list.map((m) => (
              <li key={m.clip + m.issue}>
                <Link href={`/review/${m.clip}?role=qa&issue=${m.issue}`} className="grid grid-cols-[52px_92px_1fr_auto] items-center gap-2 py-1.5 hover:bg-surface-2/60">
                  <span className="num font-semibold text-accent">{fmt(m.t)}</span>
                  <span className="truncate" style={{ color: STATUS[m.severity === "fix" ? "fix" : "check"].color }}>{KIND_LABEL[m.kind] ?? m.kind}</span>
                  <span className="truncate text-ink-2">{m.title_text}<span className="text-muted"> · {m.title}</span></span>
                  {m.fixable && <span className="rounded bg-accent/15 px-1.5 text-[10px] text-accent">auto-fixable</span>}
                </Link>
              </li>
            ))}
          </ul>
          {a.mistakes.length > 8 && (
            <button onClick={() => setShowAll((v) => !v)} className="mt-1 text-xs text-accent hover:underline">
              {showAll ? "Show fewer" : `Show all ${a.mistakes.length}`}
            </button>
          )}
        </div>
      </div>
    </li>
  );
}
type BatchStats = {
  total_clips: number; analyzed: number; running: number;
  total_segments: number; total_issues: number; fix: number; check: number; pass: number;
  footage_minutes: number; analysis_seconds: number; avg_realtime_factor: number | null;
};

function Bar({ s }: { s: NonNullable<ClipRow["summary"]> }) {
  const n = Math.max(1, s.segments);
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-surface-2">
      {(["pass", "check", "fix"] as const).map((k) => (
        <div key={k} style={{ width: `${(100 * s[k]) / n}%`, background: STATUS[k].color }} />
      ))}
    </div>
  );
}

export default function QAPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [stats, setStats] = useState<BatchStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [returnNote, setReturnNote] = useState<Record<string, string>>({});
  const [qa, setQA] = useState<QAReport | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const load = useCallback(() => {
    getJSON<Row[]>("/clips").then(setRows).catch((e) => setError(e.message));
    getJSON<BatchStats>("/batch/stats").then(setStats).catch(() => {});
    getJSON<QAReport>("/qa/report").then(setQA).catch(() => {});
  }, []);

  async function autofix(id: string) {
    setBusy(id);
    try {
      const r = await postJSON<{ autofixed: number }>(`/clips/${id}/autofix`);
      setFlash(r.autofixed ? `Auto-fixed ${r.autofixed} issue${r.autofixed > 1 ? "s" : ""} and re-checked the clip.` : "Nothing left that can be fixed automatically.");
      load();
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!rows?.some((r) => r.job?.status === "running")) return;
    const t = setTimeout(load, 1500);
    return () => clearTimeout(t);
  }, [rows, load]);

  async function runAll() {
    try { await postJSON("/batch/analyze"); load(); } catch (e) { setError((e as Error).message); }
  }

  async function approve(id: string) {
    try { await postJSON(`/clips/${id}/workflow`, { action: "approve" }); load(); } catch (e) { setError((e as Error).message); }
  }

  async function sendBack(id: string) {
    const note = returnNote[id] || "Please review the flagged issues and resubmit.";
    try { await postJSON(`/clips/${id}/workflow`, { action: "return", note }); load(); } catch (e) { setError((e as Error).message); }
  }

  const submitted = rows?.filter((r) => r.workflow?.status === "submitted") ?? [];
  const returned = rows?.filter((r) => r.workflow?.status === "returned") ?? [];
  const approved = rows?.filter((r) => r.workflow?.status === "approved") ?? [];
  const drafts = rows?.filter((r) => !r.workflow || r.workflow.status === "draft") ?? [];

  return (
    <div className="sim min-h-screen bg-bg text-ink">
      <AppHeader />
      <main className="mx-auto max-w-[1600px] px-4 pb-24 pt-8 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <p className="eyebrow">QA desk</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Quality review</h1>
            <p className="mt-2 max-w-2xl text-ink-2">
              Review submitted annotations. SoloSim shows you every mistake per timestamp — approve clean batches,
              or send back to the annotator with specific notes on what to fix.
            </p>
          </div>
          {drafts.length > 0 && (
            <button onClick={runAll} className="btn btn-primary">
              <Play className="h-4 w-4" /> Analyze all unprocessed
            </button>
          )}
        </div>

        {error && <p className="mt-4 rounded-lg bg-collision/15 px-3 py-2 text-sm" role="alert">{error}</p>}

        {stats && stats.analyzed > 0 && (
          <Reveal className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-[14px] border border-line bg-line text-center shadow-[var(--shadow-1)] sm:grid-cols-3 lg:grid-cols-6">
            {([
              ["Total clips", stats.total_clips, 0, ""],
              ["Segments", stats.total_segments, 0, ""],
              ["Issues found", stats.total_issues, 0, ""],
              ["Need fixing", stats.fix, 0, ""],
              ["Auto-passed", stats.pass, 0, ""],
              ["Analysis speed", stats.avg_realtime_factor ?? 0, 1, "× RT"],
            ] as const).map(([k, v, dp, suffix]) => (
              <div key={k} className="bg-surface px-3 py-3.5">
                <div className="text-[11px] text-muted">{k}</div>
                <div className="num mt-0.5 text-xl font-semibold"><Count to={v} decimals={dp} suffix={suffix} /></div>
              </div>
            ))}
          </Reveal>
        )}

        {flash && <p className="mt-4 rounded-lg bg-clear/15 px-3 py-2 text-sm" role="status">{flash}</p>}

        {qa && qa.annotators.length > 0 && (
          <section className="mt-8">
            <h2 className="text-lg font-semibold">Mistake report by annotator</h2>
            <p className="text-xs text-muted">Who made which mistake, at which second, and how often, across every submitted clip.</p>
            <ul className="mt-3 space-y-3">
              {qa.annotators.map((a) => <MistakeReport key={a.annotator} a={a} />)}
            </ul>
          </section>
        )}

        {rows && rows.length > 0 && submitted.length + returned.length + approved.length === 0 && (
          <p className="mt-8 rounded-xl border border-dashed border-line p-6 text-center text-sm text-muted">
            Nothing submitted yet. A clip shows up here once its annotator presses <b className="text-ink">Submit to QA</b>.
          </p>
        )}

        {/* Submitted — ready for QA */}
        {submitted.length > 0 && (
          <section className="mt-8">
            <h2 className="flex items-center gap-2 text-lg font-semibold"><ShieldCheck className="h-5 w-5 text-accent" /> Ready for review ({submitted.length})</h2>
            <Stagger className="mt-3 space-y-3">
              {submitted.map((r) => (
                <Item key={r.id} className="card card-lift border-accent/30 bg-accent-soft/50 p-4">
                  <div className="grid grid-cols-[132px_1fr] gap-4 sm:grid-cols-[200px_1fr_auto]">
                    <Link href={`/review/${r.id}?role=qa`} className="stage relative block overflow-hidden rounded-xl" style={{ aspectRatio: `${r.width} / ${r.height}` }}>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={`/engine/clips/${r.id}/frame.jpg?t=${(r.duration / 3).toFixed(1)}&w=400`} alt="" className="h-full w-full object-cover" loading="lazy" />
                      <span className="num absolute bottom-1 right-1 rounded bg-black/70 px-1.5 text-[10px] text-white">{fmt(r.duration)}</span>
                    </Link>
                    <div className="min-w-0">
                      <div className="flex items-baseline gap-2">
                        <Link href={`/review/${r.id}?role=qa`} className="truncate font-semibold hover:underline">{r.title}</Link>
                        <span className="text-xs text-muted">by {r.workflow?.annotator ?? "unknown"}{r.workflow?.version && r.workflow.version > 1 ? ` · resubmission v${r.workflow.version}` : ""}</span>
                      </div>
                      {r.summary && (
                        <div className="mt-2 space-y-1.5">
                          <Bar s={r.summary} />
                          <p className="num text-xs text-ink-2">
                            <b className="text-collision">{r.summary.fix} to fix</b> · <b>{r.summary.check} to check</b> · {r.summary.pass} auto-passed · readiness {r.summary.readiness}/100
                          </p>
                          {r.timing && r.timing.seconds > 0 && (
                            <p className="num text-[11px] text-accent">Analyzed in {r.timing.seconds.toFixed(1)}s</p>
                          )}
                        </div>
                      )}
                      <div className="mt-3 flex items-center gap-2">
                        <input value={returnNote[r.id] ?? ""} onChange={(e) => setReturnNote((n) => ({ ...n, [r.id]: e.target.value }))}
                          placeholder="Note for annotator (optional)" className="flex-1 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-xs text-ink" />
                      </div>
                    </div>
                    <div className="col-span-2 grid grid-cols-2 gap-2 sm:col-span-1 sm:flex sm:flex-col sm:items-stretch sm:justify-center">
                      <Link href={`/review/${r.id}?role=qa`} className="btn btn-quiet">
                        Inspect <ArrowRight className="h-4 w-4" />
                      </Link>
                      <button onClick={() => autofix(r.id)} disabled={busy === r.id} className="btn btn-quiet">
                        {busy === r.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4 text-accent" />} Auto-fix
                      </button>
                      <button onClick={() => approve(r.id)} className="btn bg-clear text-white hover:brightness-110">
                        <CheckCircle2 className="h-4 w-4" /> Approve
                      </button>
                      <button onClick={() => sendBack(r.id)} className="btn border-warning text-warning hover:bg-warning/10">
                        <RotateCcw className="h-4 w-4" /> Return
                      </button>
                    </div>
                  </div>
                </Item>
              ))}
            </Stagger>
          </section>
        )}

        {/* Returned — waiting for annotator */}
        {returned.length > 0 && (
          <section className="mt-8">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-warning"><RotateCcw className="h-5 w-5" /> Returned to annotator ({returned.length})</h2>
            <ul className="mt-3 space-y-2">
              {returned.map((r) => {
                const lastReturn = [...(r.workflow?.history ?? [])].reverse().find((h) => h.action === "return");
                return (
                  <li key={r.id} className="card card-lift flex items-center gap-4 p-3">
                    <Link href={`/review/${r.id}?role=qa`} className="truncate font-semibold hover:underline">{r.title}</Link>
                    <span className="text-xs text-muted">by {r.workflow?.annotator}</span>
                    {lastReturn?.note && <span className="truncate text-xs text-warning">Note: {lastReturn.note}</span>}
                    <span className="ml-auto text-xs text-muted">{lastReturn?.at}</span>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {/* Approved */}
        {approved.length > 0 && (
          <section className="mt-8">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-clear"><CheckCircle2 className="h-5 w-5" /> Approved ({approved.length})</h2>
            <ul className="mt-3 space-y-2">
              {approved.map((r) => (
                <li key={r.id} className="card flex items-center gap-4 border-clear/25 bg-clear/5 p-3">
                  <Link href={`/review/${r.id}?role=qa`} className="truncate font-semibold hover:underline">{r.title}</Link>
                  <span className="text-xs text-muted">by {r.workflow?.annotator}</span>
                  {r.summary && <span className="num text-xs text-clear">readiness {r.summary.readiness}/100</span>}
                  <a href={`/engine/clips/${r.id}/export`} className="ml-auto text-xs text-accent hover:underline">Export JSON</a>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Drafts — not yet submitted */}
        {drafts.length > 0 && (
          <section className="mt-8">
            <h2 className="text-lg font-semibold text-muted">Not yet submitted ({drafts.length})</h2>
            <ul className="mt-3 space-y-2">
              {drafts.map((r) => {
                const running = r.job?.status === "running";
                return (
                  <li key={r.id} className="card card-lift flex items-center gap-4 p-3">
                    <Link href={`/review/${r.id}?role=qa`} className="truncate font-semibold hover:underline">{r.title}</Link>
                    <span className="text-xs text-muted">{r.segments} segments</span>
                    {r.summary ? (
                      <span className="num text-xs text-ink-2">{r.summary.fix} issues · readiness {r.summary.readiness}/100</span>
                    ) : running ? (
                      <span className="flex items-center gap-1 text-xs"><Loader2 className="h-3 w-3 animate-spin text-accent" /> Analyzing...</span>
                    ) : (
                      <span className="text-xs text-muted">Not analyzed</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        )}
      </main>
    </div>
  );
}
