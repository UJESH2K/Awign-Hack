"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Download, Loader2, Play, Plus, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { AppHeader } from "@/components/Brand";
import { IssueCard } from "@/components/review/IssueCard";
import { Player, type PlayerHandle } from "@/components/review/Player";
import { RenderPanel } from "@/components/review/RenderPanel";
import { Timeline } from "@/components/review/Timeline";
import { ENGINE_URL, STATUS, fmt, getJSON, postJSON, type ClipDetail, type Issue, type LabelOpinion, type Track } from "@/lib/solosim";

const FILTERS = ["open", "fix", "check", "done", "all"] as const;

function Opinion({ o, title }: { o: LabelOpinion; title: string }) {
  const bad = o.verdict.startsWith("wrong") || o.verdict === "not visible";
  return (
    <div className="rounded-lg bg-surface-2 p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted">{title}</span>
        <span className={`text-xs font-semibold uppercase ${bad ? "text-warning" : o.verdict === "correct" ? "text-clear" : "text-muted"}`}>{o.verdict}</span>
      </div>
      {o.observed_action && <p className="mt-1">Sees: <b>{o.observed_action}</b></p>}
      {o.explanation && <p className="mt-0.5 text-xs text-ink-2">{o.explanation}</p>}
    </div>
  );
}

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const [d, setD] = useState<ClipDetail | null>(null);
  const [track, setTrack] = useState<Track | null>(null);
  const [time, setTime] = useState(0);
  const [focus, setFocus] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("open");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [claude, setClaude] = useState<Record<string, LabelOpinion>>({});
  const [claudeBusy, setClaudeBusy] = useState<string | null>(null);
  const [draftLabel, setDraftLabel] = useState<{ id: string; text: string } | null>(null);
  const player = useRef<PlayerHandle>(null);
  const lastT = useRef(0);

  const load = useCallback(async () => {
    try {
      const r = await getJSON<ClipDetail>(`/clips/${id}`);
      setD(r);
      if (r.report) getJSON<Track>(`/clips/${id}/track`).then(setTrack).catch(() => {});
      return r;
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    Promise.resolve().then(load);
  }, [load]);

  // Poll while the gate is running.
  useEffect(() => {
    if (d?.job?.status !== "running") return;
    const t = setTimeout(load, 1200);
    return () => clearTimeout(t);
  }, [d, load]);

  const onTime = useCallback((t: number) => {
    if (Math.abs(t - lastT.current) > 0.08) {
      lastT.current = t;
      setTime(t);
    }
  }, []);

  const rep = d?.report;
  const segs = useMemo(() => d?.segments ?? [], [d]);
  const segById = useMemo(() => Object.fromEntries(segs.map((s) => [s.id, s])), [segs]);
  const decidedIssue = useMemo(() => {
    const m: Record<string, string> = {};
    for (const x of d?.review.decisions ?? []) if (x.issue) m[x.issue] = x.action === "apply" ? "fixed" : x.action === "accept" ? "accepted" : x.action === "reject" ? "dropped" : x.action;
    return m;
  }, [d]);
  const issues = useMemo(() => [...(rep?.issues ?? [])].sort((a, b) => a.t - b.t), [rep]);
  const shown = issues.filter((i) =>
    filter === "all" ? true : filter === "done" ? decidedIssue[i.id] : filter === "open" ? !decidedIssue[i.id] : i.severity === filter && !decidedIssue[i.id]);
  const open = issues.filter((i) => !decidedIssue[i.id]);
  const focused = issues.find((i) => i.id === focus) ?? null;
  const sel = selected ? segById[selected] : null;

  const goto = useCallback((i: Issue) => {
    setFocus(i.id);
    if (i.segment) setSelected(i.segment);
    player.current?.seek(Math.max(0, i.t - 0.4));
  }, []);

  // Keyboard: N = next open issue.
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT" || (e.target as HTMLElement).tagName === "TEXTAREA") return;
      if (e.key === "n" || e.key === "N") {
        const after = open.find((i) => i.t > (focused?.t ?? -1) && i.id !== focus) ?? open[0];
        if (after) goto(after);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, focused, focus, goto]);

  async function analyze() {
    setError(null);
    try {
      await postJSON(`/clips/${id}/analyze`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function decide(i: Issue, action: "apply" | "accept" | "reject") {
    setBusy(true);
    setError(null);
    try {
      const r = await postJSON<ClipDetail>(`/clips/${id}/decide`, { issue: i.id, segment: i.segment, action });
      setD(r);
      const next = (r.report?.issues ?? []).filter((x) => !r.review.decisions.some((dd) => dd.issue === x.id)).sort((a, b) => a.t - b.t).find((x) => x.t >= i.t);
      if (next) goto(next);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function edit(body: { segment?: string; action: "edit" | "reject" | "add"; values?: Record<string, unknown> }) {
    setBusy(true);
    setError(null);
    try {
      const r = await postJSON<ClipDetail>(`/clips/${id}/decide`, { values: {}, ...body });
      setD(r);
      if (body.action === "reject") setSelected(null);
      if (body.action === "add") {
        const added = r.segments.find((x) => !segs.some((y) => y.id === x.id));
        if (added) setSelected(added.id);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function askClaude(sid: string) {
    setClaudeBusy(sid);
    setError(null);
    try {
      const r = await postJSON<{ result: LabelOpinion; spend: ClipDetail["spend"] }>(`/clips/${id}/claude/${sid}`);
      setClaude((c) => ({ ...c, [sid]: r.result }));
      setD((x) => (x ? { ...x, spend: r.spend } : x));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setClaudeBusy(null);
    }
  }

  if (!d) {
    return (
      <div className="sim min-h-screen bg-bg text-ink">
        <AppHeader />
        <div className="grid h-[70vh] place-items-center text-muted">{error ?? <Loader2 className="h-6 w-6 animate-spin" />}</div>
      </div>
    );
  }

  const running = d.job?.status === "running";
  const s = rep?.summary;
  const claudeLeft = d.spend.available ? d.spend.left_usd : null;
  const groqOpinion = (sid: string) => rep?.label.results?.[sid];

  return (
    <div className="sim flex min-h-screen flex-col overflow-x-clip bg-bg text-ink">
      <AppHeader>
        <div className="flex min-w-0 items-center gap-3">
          <Link href="/queue" className="hidden text-sm text-muted hover:text-ink md:inline">Queue /</Link>
          <h1 className="truncate text-sm font-semibold">{d.clip.title}</h1>
          <span className="num hidden text-xs text-muted lg:inline">{fmt(d.clip.duration)} · {segs.length} segments · {d.clip.width}×{d.clip.height}</span>
        </div>
      </AppHeader>

      {error && (
        <div className="flex items-center justify-between border-b border-collision/40 bg-collision/15 px-4 py-2 text-sm" role="alert">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-muted hover:text-ink">Dismiss</button>
        </div>
      )}

      <div className="mx-auto grid w-full max-w-[1600px] flex-1 gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_420px]">
        {/* ----------------------------------------------------------- left: footage + timeline */}
        <main className="flex min-w-0 flex-col gap-3">
          {s && (
            <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-5">
              <div className="bg-surface px-4 py-2.5">
                <div className="text-[11px] text-muted">Robot-readiness</div>
                <div className="num text-2xl font-semibold">{s.readiness}<span className="text-sm text-muted">/100</span></div>
              </div>
              {(["pass", "check", "fix"] as const).map((k) => (
                <div key={k} className="bg-surface px-4 py-2.5">
                  <div className="flex items-center gap-1.5 text-[11px] text-muted"><span className="h-2 w-2 rounded-full" style={{ background: STATUS[k].color }} />{k === "pass" ? "Auto-passed" : k === "check" ? "To look at" : "To fix"}</div>
                  <div className="num text-2xl font-semibold">{s[k]}<span className="text-sm text-muted"> seg</span></div>
                </div>
              ))}
              <div className="col-span-2 bg-surface px-4 py-2.5 sm:col-span-1">
                <div className="text-[11px] text-muted">Reviewer watches</div>
                <div className="num text-2xl font-semibold">{Math.round(s.review_share * 100)}%</div>
              </div>
            </div>
          )}
          <Player ref={player} src={`${ENGINE_URL}/clips/${id}/video`} aspect={d.clip.width / d.clip.height} fps={d.clip.fps} track={track}
            segments={segs} status={rep?.status ?? {}} focus={focused} onTime={onTime} />
          {rep && (
            <div className="-mb-1 flex justify-end">
              <button disabled={busy} onClick={() => edit({ action: "add", values: { start: Number(time.toFixed(2)), end: Number(Math.min(d.clip.duration, time + 2).toFixed(2)), narration: "new action" } })}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-ink-2 hover:bg-surface-2 hover:text-ink"><Plus className="h-3.5 w-3.5" /> Add a segment at {fmt(time)}</button>
            </div>
          )}
          {rep ? (
            <Timeline duration={d.clip.duration} segments={segs} status={rep.status} issues={issues} track={track} time={time}
              selected={selected} focus={focus} onSeek={(t) => player.current?.seek(t)} onSelect={setSelected} onFocus={goto} />
          ) : (
            <div className="rounded-xl border border-dashed border-line p-6 text-center">
              {running ? (
                <div className="mx-auto max-w-md">
                  <p className="flex items-center justify-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin text-accent" /> {d.job?.stage}</p>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-2"><div className="h-full bg-accent transition-all" style={{ width: `${(d.job?.fraction ?? 0) * 100}%` }} /></div>
                </div>
              ) : (
                <>
                  <p className="text-sm text-ink-2">Not checked yet. The gate measures every frame, checks every segment, and asks an AI reviewer about every label.</p>
                  <button onClick={analyze} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-accent-fill px-4 py-2 text-sm font-semibold text-white"><Play className="h-4 w-4" /> Run the gate</button>
                </>
              )}
            </div>
          )}
          {sel && (
            <section className="grid gap-4 rounded-xl border border-line bg-surface p-4 xl:grid-cols-[minmax(0,300px)_minmax(0,1fr)]">
              <div>
                <div className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: STATUS[rep?.status[sel.id] ?? "pass"].color }} />
                  <form className="flex min-w-0 flex-1 gap-1.5"
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (draftLabel?.id === sel.id && draftLabel.text.trim()) edit({ segment: sel.id, action: "edit", values: { narration: draftLabel.text.trim() } });
                    }}>
                    <input aria-label="Label" value={draftLabel?.id === sel.id ? draftLabel.text : sel.narration}
                      onChange={(e) => setDraftLabel({ id: sel.id, text: e.target.value })}
                      className="min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-1.5 py-0.5 font-semibold hover:border-line focus:border-accent focus:bg-surface-2" />
                    {draftLabel?.id === sel.id && draftLabel.text !== sel.narration && (
                      <button disabled={busy} className="rounded-md bg-accent-fill px-2 text-xs font-semibold text-white">Save</button>
                    )}
                  </form>
                </div>
                <p className="num mt-0.5 text-xs text-muted">
                  {fmt(sel.start)} – {fmt(sel.end)} · {(sel.end - sel.start).toFixed(1)} s · verb <b>{sel.verb}</b> · object <b>{sel.noun}</b>
                  {sel.meta?.drafted_by === "ai" && <span className="ml-1 rounded bg-anomaly/30 px-1 text-[10px] text-ink">AI first pass</span>}
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                  <button disabled={busy || time >= sel.end} onClick={() => edit({ segment: sel.id, action: "edit", values: { start: Number(time.toFixed(2)) } })}
                    className="rounded-md border border-line px-2 py-1 hover:bg-surface-2 disabled:opacity-40">Start = {fmt(time)}</button>
                  <button disabled={busy || time <= sel.start} onClick={() => edit({ segment: sel.id, action: "edit", values: { end: Number(time.toFixed(2)) } })}
                    className="rounded-md border border-line px-2 py-1 hover:bg-surface-2 disabled:opacity-40">End = {fmt(time)}</button>
                  <button disabled={busy} onClick={() => edit({ segment: sel.id, action: "reject" })}
                    className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-ink-2 hover:bg-surface-2 hover:text-collision"><Trash2 className="h-3 w-3" /> Drop</button>
                </div>
                <div className="mt-3 space-y-2">
                  {groqOpinion(sel.id) && <Opinion o={groqOpinion(sel.id)!} title="AI reviewer (automatic)" />}
                  {claude[sel.id] && <Opinion o={claude[sel.id]} title="Claude (second opinion)" />}
                  {!claude[sel.id] && (
                    <button onClick={() => askClaude(sel.id)} disabled={claudeLeft === null || claudeLeft <= 0 || claudeBusy === sel.id}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-xs text-ink-2 hover:bg-surface-2 hover:text-ink disabled:opacity-40">
                      {claudeBusy === sel.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                      Ask Claude about this label · ~1¢ {claudeLeft !== null && <span className="text-muted">(${claudeLeft.toFixed(2)} left)</span>}
                    </button>
                  )}
                </div>
              </div>
              <RenderPanel clipId={id} segment={sel} />
            </section>
          )}
        </main>

        {/* ----------------------------------------------------------- right: nudges */}
        <aside className="flex min-h-0 flex-col gap-3 lg:sticky lg:top-[4.5rem] lg:max-h-[calc(100vh-5.5rem)]" aria-label="Nudges">
          <div className="rounded-xl border border-line bg-surface p-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">Nudges for the tester</h2>
              <span className="num text-xs text-muted">{issues.length - open.length}/{issues.length} handled</span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2">
              <div className="h-full bg-clear transition-all" style={{ width: `${issues.length ? (100 * (issues.length - open.length)) / issues.length : 0}%` }} />
            </div>
            <div className="mt-3 flex items-center justify-between gap-2">
              <div role="radiogroup" aria-label="Show" className="flex rounded-lg bg-surface-2 p-0.5 text-xs">
                {FILTERS.map((f) => (
                  <button key={f} role="radio" aria-checked={filter === f} onClick={() => setFilter(f)}
                    className={`rounded-md px-2 py-1 capitalize ${filter === f ? "bg-surface text-ink ring-1 ring-line" : "text-muted hover:text-ink"}`}>{f}</button>
                ))}
              </div>
              {open.length > 0 && (
                <button onClick={() => goto(open.find((i) => i.t > (focused?.t ?? -1)) ?? open[0])}
                  className="inline-flex items-center gap-1 rounded-lg bg-accent-fill px-2.5 py-1 text-xs font-semibold text-white" title="Next open issue (N)">
                  Next <ArrowRight className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
            {rep && shown.length === 0 && (
              <p className="rounded-xl border border-dashed border-line p-6 text-center text-sm text-muted">
                {open.length === 0 ? "Every nudge is handled. Export the clip for the client." : "Nothing in this filter."}
              </p>
            )}
            {shown.map((i) => (
              <IssueCard key={i.id} issue={i} segment={i.segment ? segById[i.segment] : undefined} focused={focus === i.id} decided={decidedIssue[i.id]}
                clipId={id} busy={busy} claudeLeft={claudeLeft} onFocus={() => goto(i)} onDecide={(a) => decide(i, a)}
                onClaude={i.group === "label" && i.segment ? () => askClaude(i.segment!) : undefined} />
            ))}
          </div>
          {rep && (
            <div className="flex gap-2">
              <a href={`/engine/clips/${id}/export`} className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-accent-fill px-3 py-2 text-sm font-semibold text-white hover:brightness-110">
                <Download className="h-4 w-4" /> Export for the client
              </a>
              <button onClick={analyze} disabled={running} title="Run the gate again" className="ctl h-9 w-9"><RefreshCw className={`h-4 w-4 ${running ? "animate-spin" : ""}`} /></button>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
