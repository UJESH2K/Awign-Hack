import Link from "next/link";
import { ArrowRight, Box, Camera, Clock, Crosshair, EyeOff, FileCheck2, Hand, Layers, ScanSearch, ShieldCheck, Tags } from "lucide-react";
import { Logo } from "@/components/Brand";
import { ENGINE_URL } from "@/lib/solosim";

export const dynamic = "force-dynamic";

type Bench = {
  timing: { summary: { recall: number; planted: number; false_flag_rate: number; by_kind: Record<string, { recall: number }> }; review_load: { share: number } } | null;
  labels: Record<string, { recall: number; false_flag_rate: number; segments: number } | null>;
};

async function bench(): Promise<Bench | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/bench`, { cache: "no-store", signal: AbortSignal.timeout(2500) });
    return r.ok ? r.json() : null;
  } catch {
    return null;
  }
}

const PIPELINE = [
  { icon: Camera, title: "Capture", body: "Workers record tasks on head-mounted cameras." },
  { icon: Tags, title: "Annotate", body: "A VLM first pass, then annotators set start, end, verb and object." },
  { icon: ScanSearch, title: "SoloSim gate", body: "Every segment checked against the pixels. Exact error, exact fix.", hi: true },
  { icon: FileCheck2, title: "QA tester", body: "Opens only what was flagged, starting at the wrong moment." },
  { icon: Box, title: "Client", body: "Robot-ready data, with the QA trail for every segment." },
];

const CHECKS = [
  { icon: Clock, title: "Timing", body: "Overlapping segments, starts before the hands move, ends after they stop, mistyped end times, and hand activity nobody labelled." },
  { icon: Tags, title: "Labels", body: "An AI reviewer looks at every segment: does the footage show this verb on this object? It names what it actually sees. Claude gives a deeper second opinion on request." },
  { icon: Hand, title: "Capture", body: "Blur from head motion, frames too dark, the camera whipping away, hands off-screen during a manipulation label." },
  { icon: EyeOff, title: "Privacy", body: "Bystander faces that must be blurred before the clip leaves QA." },
  { icon: Box, title: "World-model test", body: "LingBot World 2 renders the annotation in first person from the real first frame. Where it loses the hands or the object, the segment is not a usable robot scenario yet." },
  { icon: Crosshair, title: "The nudge", body: "Each issue arrives as one sentence, the frame with the box drawn on it, and a one-click fix: “Move the end of ‘take cup’ to 0:02.9.”" },
];

export default async function Landing() {
  const b = await bench();
  const t = b?.timing;
  const lab = b?.labels?.groq ?? null;
  return (
    <div className="min-h-screen overflow-x-clip">
      <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur">
        <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-6 px-4 sm:px-6" aria-label="Main">
          <Logo className="text-lg" />
          <div className="hidden items-center gap-6 text-sm text-ink-2 md:flex">
            <a href="#problem" className="hover:text-ink">The problem</a>
            <a href="#checks" className="hover:text-ink">What it checks</a>
            <a href="#evidence" className="hover:text-ink">Evidence</a>
            <a href="#industry" className="hover:text-ink">Why it matters</a>
          </div>
          <Link href="/queue" className="inline-flex items-center gap-2 rounded-lg bg-ink px-4 py-2 text-sm font-medium text-bg hover:opacity-90">
            Open the queue <ArrowRight className="h-4 w-4" />
          </Link>
        </nav>
      </header>

      <main>
        <section className="mx-auto max-w-6xl px-4 pb-16 pt-14 sm:px-6 lg:pt-20">
          <p className="eyebrow">Physical AI · data quality</p>
          <h1 className="mt-4 max-w-4xl text-4xl font-semibold leading-[1.08] tracking-tight sm:text-5xl lg:text-[3.6rem]">
            Robot training data, checked before QA ever opens it.
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-ink-2">
            SoloSim watches every annotated segment of first-person footage, finds the exact moment a label is wrong, and hands
            the tester the fix. Then it renders the annotation in a world model to see whether a robot could learn from it.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/queue" className="inline-flex items-center gap-2 rounded-lg bg-accent-fill px-5 py-3 font-medium text-accent-ink hover:opacity-90">
              Review a clip <ArrowRight className="h-4 w-4" />
            </Link>
            <Link href="/bench" className="inline-flex items-center gap-2 rounded-lg border border-line-strong px-5 py-3 font-medium hover:bg-surface-2">
              See the evidence
            </Link>
          </div>
          {t && (
            <dl className="mt-12 grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3">
              <div className="bg-surface p-5">
                <dt className="text-sm text-ink-2">planted annotation errors caught from the pixels alone</dt>
                <dd className="num mt-1 text-4xl font-semibold tracking-tight">{Math.round(t.summary.recall * 100)}%</dd>
                <dd className="num text-xs text-muted">{t.summary.planted} errors, real EPIC-KITCHENS footage</dd>
              </div>
              <div className="bg-surface p-5">
                <dt className="text-sm text-ink-2">false flags on untouched segments</dt>
                <dd className="num mt-1 text-4xl font-semibold tracking-tight">{(t.summary.false_flag_rate * 100).toFixed(1)}%</dd>
                <dd className="text-xs text-muted">testers are not buried in noise</dd>
              </div>
              <div className="bg-surface p-5">
                <dt className="text-sm text-ink-2">{lab ? "wrong labels flagged by the AI reviewer" : "mistyped end times caught"}</dt>
                <dd className="num mt-1 text-4xl font-semibold tracking-tight">{Math.round((lab ? lab.recall : t.summary.by_kind.truncated?.recall ?? 0) * 100)}%</dd>
                <dd className="text-xs text-muted">{lab ? `${lab.segments} segments, free hosted vision model` : "every one"}</dd>
              </div>
            </dl>
          )}
        </section>

        <section id="problem" className="scroll-mt-20 border-y border-line bg-surface">
          <div className="mx-auto grid max-w-6xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-[1fr_1.1fr]">
            <div>
              <p className="eyebrow">The problem</p>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">The bottleneck in robot data is not capture. It is checking.</h2>
            </div>
            <div className="space-y-4 text-ink-2">
              <p>
                Robots learn manipulation from people: thousands of hours of head-mounted video, every action cut into segments with a
                verb, an object, a start and an end. Awign captures more than 10,000 hours a day this way.
              </p>
              <p>
                Then someone has to check it. Labelling first-person footage reportedly takes 70 to 155 hours per hour of video, and
                QA re-watches it again. A segment that starts two seconds early, or says “take” when the hand puts down, quietly
                teaches a robot the wrong thing, and the client only finds out when a batch is rejected.
              </p>
              <p className="text-ink">
                SoloSim does the first watch automatically, so the tester only looks where something is wrong, and starts at the
                exact frame.
              </p>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <p className="eyebrow">Where it sits</p>
          <h2 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">A gate between the annotator and QA. Nothing else changes.</h2>
          <ol className="mt-10 grid gap-3 md:grid-cols-5">
            {PIPELINE.map((p, i) => (
              <li key={p.title} className={`relative rounded-xl border p-5 ${p.hi ? "border-accent bg-accent-soft" : "border-line bg-surface"}`}>
                <span className="font-mono text-xs text-muted">{String(i + 1).padStart(2, "0")}</span>
                <p.icon className={`mt-2 h-6 w-6 ${p.hi ? "text-accent" : "text-ink-2"}`} aria-hidden />
                <h3 className="mt-2 font-semibold">{p.title}</h3>
                <p className="mt-1 text-sm text-ink-2">{p.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="checks" className="scroll-mt-20 border-y border-line bg-surface">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
            <p className="eyebrow">What it checks, per segment</p>
            <h2 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">Every flag says where, what, and how to fix it.</h2>
            <ul className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {CHECKS.map((c) => (
                <li key={c.title} className="rounded-xl border border-line bg-bg p-5">
                  <c.icon className="h-6 w-6 text-accent" aria-hidden />
                  <h3 className="mt-3 font-semibold">{c.title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{c.body}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="evidence" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
          <div className="grid gap-10 lg:grid-cols-[1fr_1fr]">
            <div>
              <p className="eyebrow">Evidence</p>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">Measured on real footage with planted errors.</h2>
              <p className="mt-4 text-ink-2">
                EPIC-KITCHENS-100: head-mounted video with official action segments. We plant the slips annotators make (shifted
                boundaries, mistyped times, missed actions, copied labels), run the gate, and count. The numbers on this page are read
                live from the last benchmark run.
              </p>
              <Link href="/bench" className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-accent hover:underline">
                Full benchmark and method <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
            <ul className="space-y-3">
              {t && Object.entries(t.summary.by_kind).map(([k, v]) => (
                <li key={k}>
                  <div className="flex justify-between text-sm"><span className="capitalize">{k}</span><span className="num font-semibold">{Math.round(v.recall * 100)}%</span></div>
                  <div className="mt-1 h-2.5 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-accent" style={{ width: `${v.recall * 100}%` }} /></div>
                </li>
              ))}
              {lab && (
                <li>
                  <div className="flex justify-between text-sm"><span>Wrong label (AI reviewer)</span><span className="num font-semibold">{Math.round(lab.recall * 100)}%</span></div>
                  <div className="mt-1 h-2.5 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-accent" style={{ width: `${lab.recall * 100}%` }} /></div>
                </li>
              )}
              {!t && <li className="text-sm text-muted">Start the engine to show the latest numbers.</li>}
            </ul>
          </div>
        </section>

        <section id="industry" className="scroll-mt-20 border-y border-line bg-surface">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
            <p className="eyebrow">Why it matters</p>
            <h2 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">Cheaper checking, better robots, faster feedback.</h2>
            <div className="mt-10 grid gap-4 md:grid-cols-3">
              {[
                { icon: Layers, h: "For the data company", p: "QA time goes to flagged segments only, fewer batches bounce back, and every delivered segment carries its QA trail. A “robot-ready” tier becomes something you can measure and sell." },
                { icon: Box, h: "For robotics teams", p: "Fewer mislabelled segments in training sets, and a world-model render that shows which annotated actions reproduce as scenarios before anyone trains on them." },
                { icon: ShieldCheck, h: "For the people capturing", p: "Feedback in minutes instead of a rejected batch weeks later: keep your hands in view, slow the head turn, re-shoot this one task." },
              ].map((x) => (
                <div key={x.h} className="rounded-xl border border-line bg-bg p-5">
                  <x.icon className="h-6 w-6 text-accent" aria-hidden />
                  <h3 className="mt-3 font-semibold">{x.h}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{x.p}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <div className="grid gap-10 lg:grid-cols-[1fr_1.4fr]">
            <div>
              <p className="eyebrow">Honest limits</p>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight">Said before anyone asks.</h2>
            </div>
            <dl className="space-y-5">
              {[
                ["Does it replace QA?", "No. It decides where QA looks first and what to check. Every label flag is a suggestion; the tester decides."],
                ["How accurate is the label check?", "Measured on the Evidence page with planted wrong labels. It disagrees with some original labels too; many of those are loose narrations, which a tester should see anyway."],
                ["Why low resolution in the demo?", "The public EPIC copy is 456×256. Awign captures in 4K, which gives the hand and face detectors far more to work with."],
                ["Is the world-model render physics?", "No. It shows whether the annotated action reproduces as a coherent first-person scene, and where it breaks. It is a scenario check, not a simulation."],
              ].map(([q, a]) => (
                <div key={q}>
                  <dt className="font-semibold">{q}</dt>
                  <dd className="mt-1 text-ink-2">{a}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
          <div className="flex flex-col items-start justify-between gap-6 rounded-2xl bg-[#0b0c0e] p-8 text-white sm:flex-row sm:items-center sm:p-10">
            <div>
              <h2 className="text-3xl font-semibold tracking-tight">Open a clip and fix it.</h2>
              <p className="mt-2 text-white/70">Four real first-person videos are waiting in the queue. Upload your own with its annotations.</p>
            </div>
            <Link href="/queue" className="inline-flex items-center gap-2 rounded-lg bg-white px-5 py-3 font-medium text-[#0b0c0e] hover:opacity-90">
              Open the review queue <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </section>
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-8 text-sm text-muted sm:flex-row sm:justify-between sm:px-6">
          <span>SoloSim · Awign Physical AI Hackathon, Bengaluru, October 2026</span>
          <span>Footage: EPIC-KITCHENS-100 (CC BY-NC 4.0). World model: Reactor LingBot World 2.</span>
        </div>
      </footer>
    </div>
  );
}
