import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  BadgeCheck,
  Clock,
  Film,
  ImageIcon,
  Info,
  MonitorPlay,
  RotateCcw,
  ScanSearch,
} from "lucide-react";
import type { TaskInfo } from "../types";
import { detectPreviewUrl, originalUrl, resultUrl } from "../api";
import { cn, platformName } from "../lib/utils";
import CompareSlider from "./CompareSlider";
import VideoCompare from "./VideoCompare";
import SaveActions from "./SaveActions";

interface Props {
  task: TaskInfo;
  onReset: () => void;
}

export default function ResultView({ task, onReset }: Props) {
  const [showDetect, setShowDetect] = useState(false);
  const isVideo = task.media_type === "video";
  const count = isVideo
    ? (task.meta.detected_tracks ?? task.tracks.length)
    : (task.meta.detected_count ?? task.regions.length);
  const found = task.meta.watermark_found ?? count > 0;
  const before = originalUrl(task);
  const after = resultUrl(task);
  const preview = detectPreviewUrl(task);
  const pf = platformName(task.meta.platform);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-7"
    >
      {/* 结果头 */}
      <div className="flex flex-col items-center gap-3 text-center">
        <div
          className={cn(
            "flex h-14 w-14 items-center justify-center rounded-2xl",
            found
              ? "bg-emerald-500/15 text-emerald-400 shadow-[0_0_30px_-5px_rgba(16,185,129,0.4)]"
              : "bg-sky-500/15 text-sky-400",
          )}
        >
          {found ? <BadgeCheck className="h-8 w-8" /> : <Info className="h-8 w-8" />}
        </div>
        <h2 className="text-2xl font-semibold text-slate-100">
          {found ? "水印去除完成" : "未检测到明显水印"}
        </h2>
        <p className="max-w-md text-sm leading-relaxed text-slate-400">
          {found
            ? `共识别并移除 ${count} 处${isVideo ? "水印轨迹" : "水印区域"}，请对比确认效果后再保存`
            : "画面中未发现明显水印，已为你输出原画质副本"}
        </p>
      </div>

      {/* 信息 chips */}
      <div className="flex flex-wrap items-center justify-center gap-2 text-xs text-slate-300">
        <span className="glass-card flex items-center gap-1.5 rounded-full px-3 py-1.5">
          {isVideo ? (
            <Film className="h-3.5 w-3.5 text-violet-300" />
          ) : (
            <ImageIcon className="h-3.5 w-3.5 text-violet-300" />
          )}
          {isVideo ? "视频" : "图片"}
        </span>
        {pf && <span className="glass-card rounded-full px-3 py-1.5">{pf}</span>}
        {isVideo && task.meta.duration ? (
          <span className="glass-card flex items-center gap-1.5 rounded-full px-3 py-1.5">
            <Clock className="h-3.5 w-3.5 text-slate-400" />
            {task.meta.duration}s
          </span>
        ) : null}
        {isVideo && task.meta.width ? (
          <span className="glass-card flex items-center gap-1.5 rounded-full px-3 py-1.5">
            <MonitorPlay className="h-3.5 w-3.5 text-slate-400" />
            {task.meta.width}×{task.meta.height}
          </span>
        ) : null}
        {isVideo &&
          task.tracks.map((t, i) => (
            <span
              key={`${t.x1}-${t.t0}-${i}`}
              className="glass-card rounded-full px-3 py-1.5 text-slate-400"
            >
              水印{i + 1}：{t.t0.toFixed(1)}s–{t.t1.toFixed(1)}s
            </span>
          ))}
      </div>

      {/* 对比区 */}
      {before &&
        after &&
        (isVideo ? (
          <VideoCompare before={before} after={after} />
        ) : (
          <CompareSlider before={before} after={after} />
        ))}

      {/* AI 检测标记 */}
      {preview && (
        <div className="text-center">
          <button
            onClick={() => setShowDetect((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm text-violet-300 transition hover:text-violet-200"
          >
            <ScanSearch className="h-4 w-4" />
            {showDetect ? "收起检测标记" : "查看 AI 检测标记"}
          </button>
          <AnimatePresence>
            {showDetect && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden"
              >
                <img
                  src={preview}
                  alt="AI 检测标记"
                  className="mx-auto mt-4 max-h-[52vh] max-w-full rounded-2xl border border-white/10 object-contain"
                />
                <p className="mt-2.5 text-xs text-slate-500">
                  红框为算法识别到的水印区域（含外扩安全边距）
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* 保存操作：先预览，确认后再保存 */}
      <SaveActions task={task} />

      <div className="text-center">
        <button
          onClick={onReset}
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 transition hover:text-white"
        >
          <RotateCcw className="h-4 w-4" />
          再处理一个文件
        </button>
      </div>
    </motion.div>
  );
}
