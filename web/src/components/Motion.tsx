"use client";

import { useEffect, useRef } from "react";
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform, type Transition } from "motion/react";
import gsap from "gsap";

const EASE_OUT: Transition = { duration: 0.5, ease: [0.22, 1, 0.36, 1] };

/** Fade and rise once, when the block scrolls into view. */
export function Reveal({
  children,
  delay = 0,
  y = 14,
  className = "",
  as = "div",
}: {
  children: React.ReactNode;
  delay?: number;
  y?: number;
  className?: string;
  as?: "div" | "section" | "li" | "span";
}) {
  const still = useReducedMotion();
  const M = motion[as];
  if (still) return <div className={className}>{children}</div>;
  return (
    <M
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ ...EASE_OUT, delay }}
    >
      {children}
    </M>
  );
}

/** Children rise one after another. Pair with <Item>. */
export function Stagger({ children, className = "", gap = 0.06 }: { children: React.ReactNode; className?: string; gap?: number }) {
  const still = useReducedMotion();
  if (still) return <div className={className}>{children}</div>;
  return (
    <motion.div
      className={className}
      initial="off"
      animate="on"
      variants={{ off: {}, on: { transition: { staggerChildren: gap } } }}
    >
      {children}
    </motion.div>
  );
}

export const ITEM = {
  off: { opacity: 0, y: 12 },
  on: { opacity: 1, y: 0, transition: EASE_OUT },
};

export function Item({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  const still = useReducedMotion();
  if (still) return <div className={className}>{children}</div>;
  return (
    <motion.div className={className} variants={ITEM}>
      {children}
    </motion.div>
  );
}

/** A number that counts up to its value, and re-counts when the value changes.
 *  Used for readiness, issue counts and the "analysed in Xs" timer, so the demo
 *  shows the figure landing rather than appearing. */
export function Count({
  to,
  decimals = 0,
  duration = 0.9,
  className = "",
  suffix = "",
}: {
  to: number;
  decimals?: number;
  duration?: number;
  className?: string;
  suffix?: string;
}) {
  const el = useRef<HTMLSpanElement>(null);
  const from = useRef(0);
  const still = useReducedMotion();
  useEffect(() => {
    const node = el.current;
    if (!node) return;
    if (still) {
      node.textContent = to.toFixed(decimals) + suffix;
      from.current = to;
      return;
    }
    const obj = { v: from.current };
    const tw = gsap.to(obj, {
      v: to,
      duration,
      ease: "power2.out",
      onUpdate: () => {
        node.textContent = obj.v.toFixed(decimals) + suffix;
      },
      onComplete: () => {
        from.current = to;
      },
    });
    return () => {
      tw.kill();
    };
  }, [to, decimals, duration, suffix, still]);
  // Empty on the server: the effect writes the first value before anyone can read it.
  return <span ref={el} className={`num ${className}`} />;
}

/** Light 3D tilt toward the pointer. Kept to a couple of degrees: it should read as
 *  depth, not as a toy. */
export function Tilt({ children, className = "", max = 5 }: { children: React.ReactNode; className?: string; max?: number }) {
  const still = useReducedMotion();
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const rx = useSpring(useTransform(y, [-0.5, 0.5], [max, -max]), { stiffness: 220, damping: 22 });
  const ry = useSpring(useTransform(x, [-0.5, 0.5], [-max, max]), { stiffness: 220, damping: 22 });
  if (still) return <div className={className}>{children}</div>;
  return (
    <motion.div
      className={className}
      style={{ rotateX: rx, rotateY: ry, transformPerspective: 1200, transformStyle: "preserve-3d" }}
      onPointerMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        x.set((e.clientX - r.left) / r.width - 0.5);
        y.set((e.clientY - r.top) / r.height - 0.5);
      }}
      onPointerLeave={() => {
        x.set(0);
        y.set(0);
      }}
    >
      {children}
    </motion.div>
  );
}

/** Progress ring for live analysis: reads as a shutter closing around the clip. */
export function Ring({ value, size = 44, label }: { value: number; size?: number; label?: string }) {
  const r = (size - 6) / 2;
  const c = 2 * Math.PI * r;
  return (
    <span className="relative inline-grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line)" strokeWidth="3" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - Math.min(1, Math.max(0, value)))}
          style={{ transition: "stroke-dashoffset 400ms cubic-bezier(0.22,1,0.36,1)" }}
        />
      </svg>
      <span className="num absolute text-[10px] font-semibold">{label ?? `${Math.round(value * 100)}%`}</span>
    </span>
  );
}
