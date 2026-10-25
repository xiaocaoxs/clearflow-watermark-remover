import { useRef, useState } from "react";
import { Pause, Play, Volume2, VolumeX } from "lucide-react";
import { cn, fmtTime } from "../lib/utils";

interface Props {
  before: string;
  after: string;
}

/** 双画面同步播放对比：左原图 / 右成品 */
export default function VideoCompare({ before, after }: Props) {
  const aRef = useRef<HTMLVideoElement>(null); // 原视频（主控）
  const bRef = useRef<HTMLVideoElement>(null); // 成品
  const [playing, setPlaying] = useState(false);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [muted, setMuted] = useState(true);

  const toggle = async () => {
    const A = aRef.current;
    const B = bRef.current;
    if (!A || !B) return;
    if (playing) {
      A.pause();
      B.pause();
      setPlaying(false);
    } else {
      B.currentTime = A.currentTime;
      try {
        await Promise.all([A.play(), B.play()]);
        setPlaying(true);
      } catch {
        /* 浏览器阻止自动播放时忽略 */
      }
    }
  };

  const seek = (v: number) => {
    const A = aRef.current;
    const B = bRef.current;
    if (A) A.currentTime = v;
    if (B) B.currentTime = v;
    setCur(v);
  };

  const toggleMute = () => setMuted((m) => !m);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-black">
          <span className="absolute left-3 top-3 z-10 rounded-full bg-rose-500/85 px-2.5 py-1 text-xs font-medium text-white shadow">
            原视频
          </span>
          <video
            ref={aRef}
            src={before}
            muted
            playsInline
            preload="metadata"
            className="max-h-[44vh] w-full object-contain"
            onLoadedMetadata={(e) => setDur(e.currentTarget.duration || 0)}
            onTimeUpdate={(e) => {
              const B = bRef.current;
              const t = e.currentTarget.currentTime;
              if (B && Math.abs(B.currentTime - t) > 0.3) B.currentTime = t;
              setCur(t);
            }}
            onEnded={() => {
              bRef.current?.pause();
              setPlaying(false);
            }}
          />
        </div>
        <div className="relative overflow-hidden rounded-2xl border border-emerald-400/25 bg-black">
          <span className="absolute left-3 top-3 z-10 rounded-full bg-emerald-500/85 px-2.5 py-1 text-xs font-medium text-white shadow">
            无水印成品
          </span>
          <video
            ref={bRef}
            src={after}
            muted={muted}
            playsInline
            preload="metadata"
            className="max-h-[44vh] w-full object-contain"
          />
        </div>
      </div>

      {/* 同步控制条 */}
      <div className="glass-card flex items-center gap-4 rounded-full px-5 py-3">
        <button
          onClick={toggle}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white shadow-lg shadow-fuchsia-500/25 transition hover:brightness-110 active:scale-95"
        >
          {playing ? (
            <Pause className="h-4.5 w-4.5" />
          ) : (
            <Play className="ml-0.5 h-4.5 w-4.5" />
          )}
        </button>
        <input
          type="range"
          min={0}
          max={dur || 0}
          step={0.05}
          value={cur}
          onChange={(e) => seek(Number(e.target.value))}
          className="min-w-0 flex-1 accent-violet-400"
        />
        <span className="shrink-0 text-xs tabular-nums text-slate-400">
          {fmtTime(cur)} / {fmtTime(dur)}
        </span>
        <button
          onClick={toggleMute}
          title={muted ? "开启成品声音" : "静音"}
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition",
            muted
              ? "text-slate-500 hover:bg-white/10 hover:text-slate-300"
              : "bg-violet-500/20 text-violet-300",
          )}
        >
          {muted ? (
            <VolumeX className="h-4.5 w-4.5" />
          ) : (
            <Volume2 className="h-4.5 w-4.5" />
          )}
        </button>
      </div>
      <p className="text-center text-xs text-slate-600">
        左右画面已同步播放，拖动进度条对比水印位置
      </p>
    </div>
  );
}
