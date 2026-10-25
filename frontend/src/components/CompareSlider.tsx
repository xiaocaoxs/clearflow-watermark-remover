import { useRef, useState, type PointerEvent } from "react";
import { ChevronsLeftRight } from "lucide-react";

interface Props {
  before: string;
  after: string;
}

/** 图片前后对比：拖动分割线查看去除效果 */
export default function CompareSlider({ before, after }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const [pos, setPos] = useState(50);

  const update = (clientX: number) => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const p = ((clientX - rect.left) / rect.width) * 100;
    setPos(Math.min(100, Math.max(0, p)));
  };

  const onDown = (e: PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    update(e.clientX);
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    if (dragging.current) update(e.clientX);
  };
  const onUp = () => {
    dragging.current = false;
  };

  return (
    <div
      ref={ref}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={onUp}
      className="relative cursor-ew-resize touch-none select-none overflow-hidden rounded-2xl border border-white/10 bg-black/40"
    >
      {/* 底层：去除后效果 */}
      <img
        src={after}
        alt="去水印效果图"
        draggable={false}
        className="block max-h-[62vh] w-full object-contain"
      />
      {/* 上层：原图（左侧裁剪） */}
      <div
        className="absolute inset-0"
        style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }}
      >
        <img
          src={before}
          alt="原始图片"
          draggable={false}
          className="block h-full w-full object-contain"
        />
      </div>

      {/* 分割线与手柄 */}
      <div
        className="absolute inset-y-0 w-0.5 bg-gradient-to-b from-violet-400 via-white to-fuchsia-400 shadow-[0_0_12px_rgba(167,139,250,0.8)]"
        style={{ left: `${pos}%` }}
      >
        <div className="absolute left-1/2 top-1/2 flex h-10 w-10 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-white/40 bg-slate-900/85 shadow-lg backdrop-blur">
          <ChevronsLeftRight className="h-4.5 w-4.5 text-white" />
        </div>
      </div>

      <span className="absolute left-3 top-3 rounded-full bg-rose-500/85 px-2.5 py-1 text-xs font-medium text-white shadow">
        原图
      </span>
      <span className="absolute right-3 top-3 rounded-full bg-emerald-500/85 px-2.5 py-1 text-xs font-medium text-white shadow">
        已去除
      </span>
    </div>
  );
}
