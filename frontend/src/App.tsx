import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Droplets,
  Film,
  ImageIcon,
  RotateCcw,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Wand2,
} from "lucide-react";
import { getTask, startProcess } from "./api";
import type { TaskCreated, TaskInfo } from "./types";
import { cn, platformName } from "./lib/utils";
import { ToastProvider } from "./components/Toast";
import ImportPanel from "./components/ImportPanel";
import ProcessingView from "./components/ProcessingView";
import ResultView from "./components/ResultView";

const TABS = [
  { key: "image", label: "图片去水印", Icon: ImageIcon },
  { key: "video", label: "视频去水印", Icon: Film },
] as const;

const FEATURES = [
  {
    Icon: ScanSearch,
    title: "智能识别",
    desc: "候选区域先验 + 形态学分析，自动锁定多平台水印位置",
  },
  {
    Icon: Wand2,
    title: "无痕修复",
    desc: "图片 inpaint 像素重建，视频 delogo 分时段精准擦除",
  },
  {
    Icon: ShieldCheck,
    title: "隐私安全",
    desc: "处理全程在本机完成，文件不会上传到任何云端",
  },
] as const;

/** 乐观任务骨架：真实状态由轮询补全 */
function skeleton(created: TaskCreated): TaskInfo {
  return {
    task_id: created.task_id,
    media_type: created.media_type === "image" ? "image" : "video",
    status: "uploaded",
    stage: "任务已创建，正在启动处理…",
    progress: 0.02,
    regions: [],
    tracks: [],
    meta: {
      platform: created.platform,
      title: created.title,
      filename: created.filename,
    },
    error: "",
    has_result: false,
    input_name: "",
    output_name: "",
    detect_preview: "",
  };
}

function Shell() {
  const [tab, setTab] = useState<"image" | "video">("video");
  const [task, setTask] = useState<TaskInfo | null>(null);

  const handleTask = useCallback(async (created: TaskCreated) => {
    const t = skeleton(created);
    setTab(t.media_type); // 链接解析可能返回与当前 Tab 不同的类型
    setTask(t);
    try {
      await startProcess(created.task_id);
    } catch {
      /* 409：已在处理中，忽略，交给轮询 */
    }
  }, []);

  const reset = useCallback(() => setTask(null), []);

  /* 轮询任务状态 */
  const taskId = task?.task_id ?? "";
  const status = task?.status ?? "";
  useEffect(() => {
    if (!taskId || status === "done" || status === "failed") return;
    let stop = false;
    const tick = async () => {
      try {
        const t = await getTask(taskId);
        if (!stop) setTask(t);
      } catch {
        /* 瞬时网络错误忽略，继续轮询 */
      }
    };
    void tick();
    const id = window.setInterval(tick, 900);
    return () => {
      stop = true;
      window.clearInterval(id);
    };
  }, [taskId, status]);

  const name = task
    ? (task.meta.title ||
        task.meta.filename ||
        (task.media_type === "video" ? "视频任务" : "图片任务"))
    : "";

  return (
    <div className="flex min-h-screen flex-col font-sans">
      {/* 顶栏 */}
      <nav className="sticky top-0 z-40 border-b border-white/5 bg-[#070a18]/70 backdrop-blur-xl">
        <div className="mx-auto flex h-16 w-full max-w-5xl items-center justify-between px-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-500 shadow-lg shadow-violet-500/25">
              <Droplets className="h-5 w-5 text-white" />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-semibold text-slate-100">
                净界 ClearFlow
              </div>
              <div className="text-[11px] text-slate-500">
                智能去水印 · 图片 & 视频
              </div>
            </div>
          </div>
          <span className="hidden rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] text-slate-400 sm:block">
            本地处理 · 隐私安全
          </span>
        </div>
      </nav>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 pb-16 pt-8 md:pt-12">
        {/* 首页：导入 */}
        {!task && (
          <>
            <div className="mb-9 text-center">
              <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-violet-400/20 bg-violet-400/10 px-4 py-1.5 text-xs text-violet-200">
                <Sparkles className="h-3.5 w-3.5" />
                无需注册 · 全程本地处理 · 支持移动水印
              </div>
              <h1 className="text-4xl font-bold tracking-tight text-slate-50 md:text-5xl">
                一键移除
                <span className="bg-gradient-to-r from-violet-400 via-fuchsia-400 to-cyan-300 bg-clip-text text-transparent">
                  平台水印
                </span>
              </h1>
              <p className="mx-auto mt-4 max-w-xl text-sm leading-relaxed text-slate-400 md:text-base">
                自动识别画面中的 TikTok / 抖音 / 小红书 Logo 与文字水印，
                智能修复背景像素，先预览效果，满意再保存
              </p>
            </div>

            {/* Tab 切换：图片 / 视频 */}
            <div className="mx-auto grid max-w-md grid-cols-2 gap-1 rounded-2xl border border-white/10 bg-white/5 p-1 backdrop-blur">
              {TABS.map((t) => {
                const isActive = tab === t.key;
                return (
                  <button
                    key={t.key}
                    onClick={() => setTab(t.key)}
                    className="relative rounded-xl px-4 py-3 text-sm font-medium outline-none transition-colors"
                  >
                    {isActive && (
                      <motion.div
                        layoutId="tab-pill"
                        transition={{ type: "spring", stiffness: 420, damping: 34 }}
                        className="absolute inset-0 rounded-xl bg-gradient-to-r from-violet-500 to-fuchsia-500 shadow-lg shadow-fuchsia-500/25"
                      />
                    )}
                    <span
                      className={cn(
                        "relative z-10 flex items-center justify-center gap-2",
                        isActive
                          ? "text-white"
                          : "text-slate-400 hover:text-slate-200",
                      )}
                    >
                      <t.Icon className="h-4.5 w-4.5" />
                      {t.label}
                    </span>
                  </button>
                );
              })}
            </div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="mt-6"
            >
              <ImportPanel mediaType={tab} onTask={handleTask} />
            </motion.div>

            <div className="mt-8 grid gap-4 sm:grid-cols-3">
              {FEATURES.map((f) => (
                <div key={f.title} className="glass-card p-5">
                  <f.Icon className="mb-3 h-6 w-6 text-violet-300" />
                  <h3 className="text-sm font-semibold text-slate-100">
                    {f.title}
                  </h3>
                  <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
                    {f.desc}
                  </p>
                </div>
              ))}
            </div>
          </>
        )}

        {/* 任务条 */}
        {task && (
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2.5">
              <span className="glass-card flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs text-slate-200">
                {task.media_type === "video" ? (
                  <Film className="h-3.5 w-3.5 text-violet-300" />
                ) : (
                  <ImageIcon className="h-3.5 w-3.5 text-violet-300" />
                )}
                {task.media_type === "video" ? "视频任务" : "图片任务"}
              </span>
              <span className="truncate text-sm text-slate-300">{name}</span>
              {task.meta.platform && (
                <span className="glass-card shrink-0 rounded-full px-3 py-1.5 text-xs text-slate-300">
                  {platformName(task.meta.platform)}
                </span>
              )}
            </div>
            <button
              onClick={reset}
              className="glass-card flex shrink-0 items-center gap-1.5 rounded-full px-4 py-2 text-xs text-slate-300 transition hover:text-white"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              重新开始
            </button>
          </div>
        )}

        {/* 处理中 / 结果 */}
        <AnimatePresence mode="wait">
          {task && task.status !== "done" && (
            <motion.div
              key="processing"
              exit={{ opacity: 0, y: -10, transition: { duration: 0.25 } }}
            >
              <ProcessingView task={task} onReset={reset} />
            </motion.div>
          )}
          {task && task.status === "done" && (
            <motion.div
              key="result"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10, transition: { duration: 0.25 } }}
            >
              <ResultView task={task} onReset={reset} />
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {/* 页脚免责声明 */}
      <footer className="border-t border-white/5 px-4 py-7 text-center text-xs leading-relaxed text-slate-600">
        本工具仅供个人学习与技术研究使用，请尊重原创作者权益，遵守各平台协议与相关法律法规。
        <br />
        <span className="text-slate-700">
          React + TypeScript + TailwindCSS · FastAPI · OpenCV · FFmpeg delogo
        </span>
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <Shell />
    </ToastProvider>
  );
}
