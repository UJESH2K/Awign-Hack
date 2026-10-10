// SoloSim: shapes returned by the engine (engine/solosim/server.py) and small shared helpers.

// JSON goes through the Next rewrite (/engine/* -> engine:8765). Video goes straight to the
// engine so the browser can seek with range requests without the proxy buffering it.
export const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8765";

export type Segment = {
  id: string;
  start: number;
  end: number;
  verb: string;
  noun: string;
  narration: string;
  meta?: Record<string, unknown>;
};

export type Suggestion = { field: "start" | "end" | "narration" | "add"; value: number | string | { start: number; end: number } };

export type Issue = {
  id: string;
  segment: string | null;
  kind: string;
  group: "timing" | "capture" | "label" | "privacy";
  severity: "fix" | "check" | "info";
  t: number;
  t_end: number | null;
  title: string;
  detail: string;
  nudge: string;
  box: number[] | null;
  suggestion: Suggestion | null;
  evidence: Record<string, unknown>;
};

export type LabelOpinion = {
  verdict: "correct" | "wrong verb" | "wrong object" | "wrong action" | "not visible" | "unsure";
  observed_action: string;
  explanation: string;
  confidence: number;
  t: number;
  backend: "groq" | "claude" | "qwen";
  segment: string;
};

export type Summary = {
  segments: number;
  pass: number;
  fix: number;
  check: number;
  issues: number;
  groups: Record<string, number>;
  hands_visible: number;
  sharp_frames: number;
  readiness: number;
  review_share: number;
};

export type ClipInfo = {
  id: string;
  title: string;
  task: string;
  duration: number;
  fps: number;
  width: number;
  height: number;
  segments: number;
  source: Record<string, string>;
};

export type Report = {
  clip: ClipInfo;
  segments: Segment[];
  status: Record<string, "pass" | "check" | "fix">;
  issues: Issue[];
  summary: Summary;
  label: { backend?: string; results?: Record<string, LabelOpinion> };
  timing?: { seconds: number; measure_seconds: number };
  generated?: string;
};

export type Decision = { at: string; segment: string | null; issue: string | null; kind: string | null; action: string; values: Record<string, unknown>; note: string };

export type Job = { status: "running" | "done" | "error" | "idle"; stage: string; fraction: number; started?: number };

export type Spend = { spent_usd: number; cap_usd: number; left_usd: number; calls: number; available: boolean };

export type ClipDetail = {
  clip: ClipInfo;
  segments: Segment[];
  report: Report | null;
  review: { decisions: Decision[]; original: Segment[] | null };
  job: Job | null;
  spend: Spend;
};

export type ClipRow = ClipInfo & { summary: Summary | null; generated: string | null; decisions: number; job: Job | null };

export type Track = {
  t: number[];
  activity: number[];
  active_on: number;
  blur: number[];
  blur_min: number;
  bright: number[];
  hands: number[][][];
  faces: number[][][];
  head_motion: number[];
};

export type RenderResult = {
  id: string;
  clip: string;
  segment: string;
  narration: string;
  prompt: string;
  start: number;
  end: number;
  chunks: number;
  real_frames: number;
  metrics: { k: number; scene: number; hands: number; hand_boxes: number[][] }[];
  judge: { verdict: string; renders_action: boolean; summary: string; failures: { frame: number; k: number; kind: string; what: string }[] };
  drift_from: number | null;
  usage?: { seconds?: number; usd?: number };
  at: string;
};

export type RenderRun = { id: string; clip: string; segment: string; status: string; stage: string; frames?: number; result?: RenderResult };

export const KIND_LABEL: Record<string, string> = {
  "too short": "Too short",
  overlap: "Overlap",
  "early start": "Starts early",
  "late end": "Ends late",
  "unlabelled activity": "Missed action",
  blur: "Blurred",
  "too dark": "Too dark",
  "camera whip": "Camera whip",
  "hands out of view": "Hands off-screen",
  face: "Face visible",
  "label mismatch": "Wrong label",
  "action not visible": "Action not visible",
};

export const GROUP_LABEL: Record<string, string> = { timing: "Timing", capture: "Capture", label: "Label", privacy: "Privacy" };

// Status colours from the validated palette: pass = clear, check = caution, fix = warning.
export const STATUS = {
  pass: { label: "Pass", color: "#0ca30c" },
  check: { label: "Check", color: "#fab219" },
  fix: { label: "Fix", color: "#f06a1d" },
} as const;

export function fmt(t: number): string {
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

export async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(`/engine${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `${r.status}`);
  return r.json();
}

export async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/engine${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(typeof data.detail === "string" ? data.detail : `Request failed (${r.status})`), { status: r.status });
  return data;
}
