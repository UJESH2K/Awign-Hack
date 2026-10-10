"use client";

import { useEffect, useState } from "react";
import { AppHeader } from "@/components/Brand";
import { getJSON } from "@/lib/solosim";

type KindScore = { caught: number; planted: number; recall: number };
type Bench = {
  timing: {
    generated: string;
    rounds: number;
    summary: { recall: number; planted: number; caught: number; by_kind: Record<string, KindScore>; false_flag_rate: number };
    review_load: { segments: number; flagged: number; share: number };
    thresholds: Record<string, number>;
  } | null;
  labels: Record<string, {
    backend: string; segments: number; wrong_caught: number; recall: number; true_flagged: number; false_flag_rate: number; true_unsure: number;
    rows: { clip: string; label: string; true_verdict: string; true_seen: string; wrong_label: string; wrong_verdict: string }[];
  } | null>;
};

const KIND_TEXT: Record<string, string> = {
  truncated: "End time mistyped (segment 0.1–0.3 s long)",
  "end late": "Segment ends 1.5–3 s after the action",
  "start early": "Segment starts 1.5–3 s before the action",
  deleted: "Action never labelled",
  "wrong label": "Label copied from another action",
};

function Bars({ items }: { items: { label: string; value: number; note: string }[] }) {
  return (
    <ul className="space-y-3">
      {items.map((it) => (
        <li key={it.label}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span>{it.label}</span>
            <span className="num font-semibold">{Math.round(it.value * 100)}%</span>
          </div>
          <div className="mt-1 h-2.5 overflow-hidden rounded-full bg-surface-2" role="img" aria-label={`${it.label}: ${Math.round(it.value * 100)}%`}>
            <div className="h-full rounded-full bg-accent" style={{ width: `${it.value * 100}%` }} />
          </div>
          <p className="num mt-0.5 text-[11px] text-muted">{it.note}</p>
        </li>
      ))}
    </ul>
  );
}

export default function BenchPage() {
  const [b, setB] = useState<Bench | null>(null);
  useEffect(() => {
    getJSON<Bench>("/bench").then(setB).catch(() => setB({ timing: null, labels: {} }));
  }, []);
  const t = b?.timing;
  const lab = b?.labels.groq ?? b?.labels.claude ?? null;
  const disagreements = (lab?.rows ?? []).filter((r) => r.true_verdict.startsWith("wrong")).slice(0, 8);

  return (
    <div className="sim min-h-screen bg-bg text-ink">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-4 pb-24 pt-8">
        <p className="eyebrow">Measured, not promised</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Evidence</h1>
        <p className="mt-2 max-w-3xl text-ink-2">
          Real first-person footage with real annotations (EPIC-KITCHENS-100, head-mounted GoPro, official action segments). We plant
          the slips annotators actually make, run the gate, and count what it catches and what it wrongly flags.
        </p>

        <section className="mt-8 grid gap-6 lg:grid-cols-2">
          <div className="rounded-xl border border-line bg-surface p-5">
            <h2 className="font-semibold">Timing errors caught from the pixels alone</h2>
            {t ? (
              <>
                <p className="mt-1 text-sm text-ink-2">
                  {t.summary.planted} errors planted in {t.rounds} rounds (20% of segments each round). No AI model involved: hand and
                  object motion, segment geometry.
                </p>
                <div className="mt-4">
                  <Bars items={Object.entries(t.summary.by_kind).map(([k, v]) => ({
                    label: KIND_TEXT[k] ?? k, value: v.recall, note: `${v.caught} of ${v.planted} caught`,
                  }))} />
                </div>
                <dl className="mt-5 grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-line bg-line text-center">
                  {[
                    ["Caught overall", `${Math.round(t.summary.recall * 100)}%`],
                    ["New false flags", `${(t.summary.false_flag_rate * 100).toFixed(1)}%`],
                    ["Original segments flagged", `${Math.round(t.review_load.share * 100)}%`],
                  ].map(([k, v]) => (
                    <div key={k} className="bg-surface-2 px-2 py-2.5">
                      <dt className="text-[11px] text-muted">{k}</dt>
                      <dd className="num text-lg font-semibold">{v}</dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-2 text-[11px] text-muted">
                  False flags: untouched segments that gained a flag. Original segments flagged: the real EPIC annotations already overlap
                  or miss activity in places; those are genuine findings for a tester, not errors of the gate.
                </p>
              </>
            ) : <p className="mt-2 text-sm text-muted">Run <code>python scripts/bench.py</code>.</p>}
          </div>

          <div className="rounded-xl border border-line bg-surface p-5">
            <h2 className="font-semibold">Wrong labels caught by the AI reviewer</h2>
            {lab ? (
              <>
                <p className="mt-1 text-sm text-ink-2">
                  Every segment checked twice: once with its real label, once with a label copied from another action in the same
                  video ({lab.segments} segments, {lab.backend === "groq" ? "Qwen 3.8 27B on Groq, free tier" : lab.backend}).
                </p>
                <div className="mt-4">
                  <Bars items={[
                    { label: "Wrong labels flagged", value: lab.recall, note: `${lab.wrong_caught} of ${lab.segments}` },
                    { label: "Real labels flagged (disagreements)", value: lab.false_flag_rate, note: `${lab.true_flagged} of ${lab.segments}; ${lab.true_unsure} marked unsure` },
                  ]} />
                </div>
                <p className="mt-3 text-[11px] text-muted">
                  A flagged real label is not always a model error: EPIC narrations are loose (“put down cup” while the cup is being
                  washed). The flag is a nudge; the tester decides.
                </p>
              </>
            ) : <p className="mt-2 text-sm text-muted">Label benchmark running…</p>}
          </div>
        </section>

        {disagreements.length > 0 && (
          <section className="mt-6 rounded-xl border border-line bg-surface p-5">
            <h2 className="font-semibold">Where the AI reviewer disagreed with the original annotation</h2>
            <table className="mt-3 w-full text-left text-sm">
              <thead className="text-xs text-muted">
                <tr className="border-b border-line"><th className="py-2 font-normal">Clip</th><th className="font-normal">Annotated</th><th className="font-normal">AI reviewer sees</th></tr>
              </thead>
              <tbody>
                {disagreements.map((r, i) => (
                  <tr key={i} className="border-b border-line last:border-0">
                    <td className="num py-2 text-muted">{r.clip}</td>
                    <td>“{r.label}”</td>
                    <td className="text-warning">{r.true_seen}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        <section className="mt-6 grid gap-4 md:grid-cols-3">
          {[
            ["What is planted", "Starts and ends shifted 1.5–3 s, end times mistyped, segments deleted, labels copied from another action. These are the slips QA sends back."],
            ["What counts as caught", "An issue of the matching kind on that segment (or, for a deleted segment, a missed-action flag over where it was)."],
            ["What it cannot do yet", "Starts that slide into the previous action without idle time, and fine verbs at 456×256. Awign's 4K capture gives the detectors far more to work with."],
          ].map(([h, p]) => (
            <div key={h} className="rounded-xl border border-line bg-surface p-4">
              <h3 className="text-sm font-semibold">{h}</h3>
              <p className="mt-1.5 text-sm text-ink-2">{p}</p>
            </div>
          ))}
        </section>
      </main>
    </div>
  );
}
