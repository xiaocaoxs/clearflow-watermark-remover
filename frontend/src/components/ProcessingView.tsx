import { motion } from "framer-motion";
import {
  AlertTriangle,
  Loader2,
  RotateCcw,
  ScanSearch,
  Wand2,
} from "lucide-react";
import type { TaskInfo } from "../types";
import { detectPreviewUrl } from "../api";

interface Props {
  task: TaskInfo;
  onReset: () => void;
}

export default function ProcessingView({ task, onReset }: Props) {
  if (task.status === "failed") {
    return (
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card mx-auto max-w-xl p-8 text-center md:p-12"
      >
        <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-rose-500/15 text-rose-400">
          <AlertTriangle className="h-8 w-8" />
        </div>
        <h2 className="text-xl font-semibold text-slate-100">处理失败</h2>
        <p className="mx-auto mt-3 max-w-md break-all rounded-xl bg-rose-500/10 px-4 py-2.5 text-sm text-rose-300">
          {task.error || "未知错误"}
        </p>
        <button
          onClick={onReset}
          className="mt-6 inline-flex items-center gap-2 rounded-xl bg-white/10 px-5 py-2.5 text-sm font-medium text-slate-200 transition hover:bg-white/15"
        >
          <RotateCcw className="h-4 w-4" />
          重新开始
        </button>
      </motion.div>
    );
  }

  const pct = Math.max(2, Math.round(task.progress * 100));
  const preview = detectPreviewUrl(task);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass-card mx-auto max-w-2xl p-8 text-center md:p-12"
    >
      <div className="relative mx-auto mb-6 h-20 w-20">
        <div className="absolute inset-0 animate-ping rounded-full bg-violet-500/20" />
        <div className="absolute inset-0 flex items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-fuchsia-500 shadow-xl shadow-fuchsia-500/30">
          <Wand2 className="h-9 w-9 text-white" />
        </div>
        <Loader2 className="absolute -right-1 -top-1 h-6 w-6 animate-spin text-fuchsia-400" />
      </div>

      <h2 className="text-xl font-semibold text-slate-100">
        {task.media_type === "video" ? "正在进行视频去水印" : "正在进行图片去水印"}
      </h2>
      <p className="mt-2 text-sm text-slate-400">{task.stage || "准备中…"}</p>

      {/* 进度条 */}
      <div className="mx-auto mt-8 max-w-md">
        <div className="relative h-2.5 overflow-hidden rounded-full bg-white/10">
          <motion.div
            animate={{ width: `${pct}%` }}
            transition={{ ease: "easeOut", duration: 0.5 }}
            className="relative h-full overflow-hidden rounded-full bg-gradient-to-r from-violet-500 to-fuchsia-400"
          >
            <span className="progress-shimmer absolute inset-0" />
          </motion.div>
        </div>
        <div className="mt-2.5 flex items-center justify-between text-xs text-slate-500">
          <span>整体进度</span>
          <span className="tabular-nums font-medium text-violet-300">{pct}%</span>
        </div>
      </div>

      {/* 检测预览（可用时展示） */}
      {preview && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="mx-auto mt-8 max-w-md"
        >
          <div className="flex items-center justify-center gap-1.5 text-xs font-medium text-emerald-300">
            <ScanSearch className="h-4 w-4" />
            已锁定水印区域（红框标记）
          </div>
          <img
            src={preview}
            alt="水印检测标记"
            className="mt-3 max-h-56 w-full rounded-xl border border-white/10 object-contain"
          />
        </motion.div>
      )}

      <p className="mt-8 text-xs text-slate-600">
        大文件处理可能需要一两分钟，请勿关闭页面
      </p>
    </motion.div>
  );
}
