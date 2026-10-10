"use client";

import { useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Maximize2, Minimize2, Pause, Play, Rewind, FastForward, Scan, RectangleHorizontal } from "lucide-react";
import { STATUS, fmt, type Issue, type Segment, type Track } from "@/lib/solosim";

export type PlayerHandle = { seek: (t: number, play?: boolean) => void; time: () => number };
export type View = "fit" | "theater";

type Props = {
  src: string;
  aspect: number; // width / height
  fps: number;
  track: Track | null;
  segments: Segment[];
  status: Record<string, "pass" | "check" | "fix">;
  focus: Issue | null;
  issues?: Issue[];
  duration?: number;
  view?: View;
  onView?: (v: View) => void;
  onTime: (t: number) => void;
  ref?: React.Ref<PlayerHandle>;
};

function nearest(ts: number[], t: number): number {
  let lo = 0;
  let hi = ts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (ts[mid] < t) lo = mid + 1;
    else hi = mid;
  }
  return lo > 0 && Math.abs(ts[lo - 1] - t) < Math.abs(ts[lo] - t) ? lo - 1 : lo;
}

/** First-person footage with what the gate saw drawn on top: hands, the issue under review, and
 *  which labelled action is active right now. Sizes like a video site — fit, theater, fullscreen —
 *  because testers watch this for hours on very different screens. */
export function Player({ src, aspect, fps, track, segments, status, focus, issues = [], duration = 0, view = "fit", onView, onTime, ref }: Props) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const shell = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [overlay, setOverlay] = useState(true);
  const [full, setFull] = useState(false);
  const [t, setT] = useState(0);
  const [loaded, setLoaded] = useState(0); // video duration, kept in state so render never reads the ref
  const raf = useRef(0);

  useImperativeHandle(ref, () => ({
    seek: (to: number, play = false) => {
      const v = video.current;
      if (!v) return;
      const go = () => {
        v.currentTime = Math.max(0, to);
        if (play) void v.play();
      };
      if (v.readyState >= 1) go();
      else v.addEventListener("loadedmetadata", go, { once: true });
    },
    time: () => video.current?.currentTime ?? 0,
  }));

  const draw = useCallback(() => {
    const v = video.current;
    const c = canvas.current;
    if (!v || !c) return;
    const now = v.currentTime;
    setT(now);
    onTime(now);
    const W = c.clientWidth;
    const H = c.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    if (c.width !== Math.round(W * dpr)) {
      c.width = Math.round(W * dpr);
      c.height = Math.round(H * dpr);
    }
    const g = c.getContext("2d")!;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    if (!overlay) return;
    g.font = "600 11px var(--font-geist-sans), system-ui";
    if (track && track.t.length) {
      const i = nearest(track.t, now);
      if (Math.abs(track.t[i] - now) < 0.3) {
        for (const b of track.hands[i] ?? []) {
          g.strokeStyle = "rgba(86, 214, 255, 0.95)";
          g.lineWidth = 1.5;
          g.setLineDash([5, 3]);
          g.strokeRect(b[0] * W, b[1] * H, (b[2] - b[0]) * W, (b[3] - b[1]) * H);
          g.setLineDash([]);
          g.fillStyle = "rgba(86, 214, 255, 0.95)";
          g.fillText("hand", b[0] * W + 3, b[1] * H - 4);
        }
      }
    }
    if (focus && focus.box && Math.abs(now - focus.t) < 0.8) {
      const [x0, y0, x1, y1] = focus.box;
      g.strokeStyle = "#ff3b55";
      g.lineWidth = 3;
      g.strokeRect(x0 * W, y0 * H, (x1 - x0) * W, (y1 - y0) * H);
      const label = focus.title;
      const tw = g.measureText(label).width + 12;
      g.fillStyle = "#ff3b55";
      g.fillRect(x0 * W, Math.max(0, y0 * H - 20), tw, 18);
      g.fillStyle = "#fff";
      g.fillText(label, x0 * W + 6, Math.max(13, y0 * H - 7));
    }
  }, [focus, onTime, overlay, track]);

  useEffect(() => {
    const loop = () => {
      draw();
      raf.current = requestAnimationFrame(loop);
    };
    raf.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf.current);
  }, [draw]);

  useEffect(() => {
    if (video.current) video.current.playbackRate = rate;
  }, [rate]);

  useEffect(() => {
    const h = () => setFull(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", h);
    return () => document.removeEventListener("fullscreenchange", h);
  }, []);

  const active = segments.filter((s) => t >= s.start && t <= s.end);
  const step = (d: number) => {
    const v = video.current;
    if (!v) return;
    v.pause();
    v.currentTime = Math.max(0, v.currentTime + d);
  };
  const toggle = () => {
    const v = video.current;
    if (!v) return;
    if (v.paused) void v.play();
    else v.pause();
  };
  const fullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void shell.current?.requestFullscreen?.();
  };

  const total = duration || loaded;
  const pct = total ? (t / total) * 100 : 0;
  // Fit leaves room for the nudge list; theater gives the footage the whole width.
  const stageMax = view === "theater" ? "min(78vh, 900px)" : "min(54vh, 620px)";

  // Player shortcuts work anywhere on the page, the way a video site behaves.
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable) return;
      if (e.key === " ") {
        e.preventDefault();
        toggle();
      } else if (e.key === "ArrowLeft") step(e.shiftKey ? -1 : -1 / fps);
      else if (e.key === "ArrowRight") step(e.shiftKey ? 1 : 1 / fps);
      else if (e.key === "f" || e.key === "F") fullscreen();
      else if (e.key === "t" || e.key === "T") onView?.(view === "theater" ? "fit" : "theater");
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  return (
    <div className="flex flex-col gap-2">
      <div
        ref={shell}
        className={`stage group relative mx-auto w-full overflow-hidden ${full ? "grid h-screen place-items-center rounded-none" : ""}`}
        style={full ? undefined : { aspectRatio: String(aspect), maxHeight: stageMax, maxWidth: `calc(${stageMax} * ${aspect})` }}
        tabIndex={0}
        aria-label="First-person footage. Space plays, arrows step a frame, shift+arrows a second, T for theater, F for fullscreen."
      >
        <div className="relative w-full" style={{ aspectRatio: String(aspect) }}>
          <video ref={video} src={src} className="absolute inset-0 h-full w-full" preload="auto" playsInline muted
            onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onClick={toggle}
            onLoadedMetadata={(e) => setLoaded(e.currentTarget.duration || 0)} />
          <canvas ref={canvas} className="pointer-events-none absolute inset-0 h-full w-full" />
          <div className="pointer-events-none absolute left-2 top-2 flex max-w-[70%] flex-col items-start gap-1">
            {active.slice(0, 3).map((s) => (
              <span key={s.id} className="inline-flex items-center gap-1.5 rounded-md bg-black/65 px-2 py-1 text-xs font-medium text-white backdrop-blur">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: STATUS[status[s.id] ?? "pass"].color }} aria-hidden />
                {s.narration}
                <span className="num text-[10px] text-white/60">{fmt(s.start)}–{fmt(s.end)}</span>
              </span>
            ))}
            {active.length === 0 && <span className="rounded-md bg-black/55 px-2 py-1 text-xs text-white/70">no label at this moment</span>}
          </div>
          <span className="num pointer-events-none absolute bottom-3 right-2 rounded bg-black/65 px-1.5 py-0.5 text-[11px] text-white">{fmt(t)}</span>
          {/* Scrubber on the footage, with every flagged moment marked. */}
          <div
            className="absolute inset-x-0 bottom-0 h-6 cursor-pointer"
            onClick={(e) => {
              if (!total) return;
              const r = e.currentTarget.getBoundingClientRect();
              const v = video.current;
              if (v) v.currentTime = ((e.clientX - r.left) / r.width) * total;
            }}
          >
            <div className="absolute inset-x-0 bottom-0 h-[3px] bg-white/20 transition-all group-hover:h-[5px]">
              <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
            </div>
            {issues.map((i) => (
              <span key={i.id} title={i.title} className="absolute bottom-0 h-[7px] w-[2px] rounded-sm"
                style={{ left: `${total ? (i.t / total) * 100 : 0}%`, background: STATUS[i.severity === "info" ? "pass" : i.severity].color }} />
            ))}
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <button onClick={() => step(-2)} className="ctl tip" data-tip="Back 2s" aria-label="Back 2 seconds"><Rewind className="h-4 w-4" /></button>
        <button onClick={() => step(-1 / fps)} className="ctl tip" data-tip="Prev frame" aria-label="Previous frame"><ChevronLeft className="h-4 w-4" /></button>
        <button onClick={toggle} className="ctl w-11 bg-ink text-bg" aria-label={playing ? "Pause" : "Play"}>
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        </button>
        <button onClick={() => step(1 / fps)} className="ctl tip" data-tip="Next frame" aria-label="Next frame"><ChevronRight className="h-4 w-4" /></button>
        <button onClick={() => step(2)} className="ctl tip" data-tip="Forward 2s" aria-label="Forward 2 seconds"><FastForward className="h-4 w-4" /></button>
        <span className="num ml-1 hidden text-xs text-muted sm:inline">{fmt(t)} / {fmt(total)}</span>
        <div role="radiogroup" aria-label="Speed" className="ml-2 flex rounded-lg border border-line bg-surface p-0.5 text-xs">
          {[0.25, 0.5, 1, 2].map((r) => (
            <button key={r} role="radio" aria-checked={rate === r} onClick={() => setRate(r)}
              className={`num rounded-md px-2 py-1 ${rate === r ? "bg-ink text-bg" : "text-muted hover:text-ink"}`}>{r}×</button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          <button onClick={() => setOverlay((o) => !o)} aria-pressed={overlay}
            className={`btn ${overlay ? "bg-accent-soft text-ink" : "btn-quiet text-muted"}`}>
            <Scan className="h-3.5 w-3.5" /> <span className="hidden sm:inline">What the gate sees</span>
          </button>
          {onView && (
            <button onClick={() => onView(view === "theater" ? "fit" : "theater")} aria-pressed={view === "theater"}
              className="ctl tip" data-tip-align="end" data-tip={view === "theater" ? "Default (T)" : "Theater (T)"} aria-label="Theater mode">
              {view === "theater" ? <Minimize2 className="h-4 w-4" /> : <RectangleHorizontal className="h-4 w-4" />}
            </button>
          )}
          <button onClick={fullscreen} className="ctl tip" data-tip-align="end" data-tip="Fullscreen (F)" aria-label="Fullscreen"><Maximize2 className="h-4 w-4" /></button>
        </div>
      </div>
    </div>
  );
}
