"use client";

import { useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Pause, Play, Rewind, FastForward, Scan } from "lucide-react";
import { STATUS, fmt, type Issue, type Segment, type Track } from "@/lib/solosim";

export type PlayerHandle = { seek: (t: number, play?: boolean) => void; time: () => number };

type Props = {
  src: string;
  aspect: number; // width / height
  fps: number;
  track: Track | null;
  segments: Segment[];
  status: Record<string, "pass" | "check" | "fix">;
  focus: Issue | null;
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
 *  which labelled action is active right now. */
export function Player({ src, aspect, fps, track, segments, status, focus, onTime, ref }: Props) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [overlay, setOverlay] = useState(true);
  const [t, setT] = useState(0);
  const raf = useRef(0);

  useImperativeHandle(ref, () => ({
    seek: (to: number, play = false) => {
      const v = video.current;
      if (!v) return;
      v.currentTime = Math.max(0, to);
      if (play) void v.play();
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

  return (
    <div
      className="flex flex-col gap-2"
      onKeyDown={(e) => {
        if ((e.target as HTMLElement).tagName === "INPUT") return;
        if (e.key === " ") {
          e.preventDefault();
          toggle();
        } else if (e.key === "ArrowLeft") step(e.shiftKey ? -1 : -1 / fps);
        else if (e.key === "ArrowRight") step(e.shiftKey ? 1 : 1 / fps);
      }}
    >
      <div className="relative mx-auto w-full overflow-hidden rounded-xl bg-black ring-1 ring-line"
        style={{ aspectRatio: String(aspect), maxWidth: `calc(52vh * ${aspect})` }} tabIndex={0}
        aria-label="First-person footage. Space plays, arrows step a frame, shift+arrows a second.">
        <video ref={video} src={src} className="absolute inset-0 h-full w-full" preload="auto" playsInline muted
          onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onClick={toggle} />
        <canvas ref={canvas} className="pointer-events-none absolute inset-0 h-full w-full" />
        <div className="pointer-events-none absolute left-2 top-2 flex max-w-[70%] flex-col items-start gap-1">
          {active.slice(0, 3).map((s) => (
            <span key={s.id} className="inline-flex items-center gap-1.5 rounded-md bg-black/70 px-2 py-1 text-xs font-medium text-white backdrop-blur">
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: STATUS[status[s.id] ?? "pass"].color }} aria-hidden />
              {s.narration}
              <span className="num text-[10px] text-white/60">{fmt(s.start)}–{fmt(s.end)}</span>
            </span>
          ))}
          {active.length === 0 && <span className="rounded-md bg-black/60 px-2 py-1 text-xs text-white/70">no label at this moment</span>}
        </div>
        <span className="num pointer-events-none absolute bottom-2 right-2 rounded bg-black/70 px-1.5 py-0.5 text-[11px] text-white">{fmt(t)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <button onClick={() => step(-2)} className="ctl" aria-label="Back 2 seconds"><Rewind className="h-4 w-4" /></button>
        <button onClick={() => step(-1 / fps)} className="ctl" aria-label="Previous frame"><ChevronLeft className="h-4 w-4" /></button>
        <button onClick={toggle} className="ctl w-10 bg-accent-fill text-white" aria-label={playing ? "Pause" : "Play"}>
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        </button>
        <button onClick={() => step(1 / fps)} className="ctl" aria-label="Next frame"><ChevronRight className="h-4 w-4" /></button>
        <button onClick={() => step(2)} className="ctl" aria-label="Forward 2 seconds"><FastForward className="h-4 w-4" /></button>
        <div role="radiogroup" aria-label="Speed" className="ml-2 flex rounded-lg bg-surface-2 p-0.5 text-xs">
          {[0.25, 0.5, 1, 2].map((r) => (
            <button key={r} role="radio" aria-checked={rate === r} onClick={() => setRate(r)}
              className={`num rounded-md px-2 py-1 ${rate === r ? "bg-surface text-ink ring-1 ring-line" : "text-muted hover:text-ink"}`}>{r}×</button>
          ))}
        </div>
        <button onClick={() => setOverlay((o) => !o)} aria-pressed={overlay}
          className={`ml-auto inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs ${overlay ? "bg-accent-soft text-ink" : "text-muted hover:text-ink"}`}>
          <Scan className="h-3.5 w-3.5" /> What the gate sees
        </button>
      </div>
    </div>
  );
}
