import { useState } from "react";
import { useDropzone } from "react-dropzone";
import { motion } from "framer-motion";
import { Film, ImageIcon, Link2, Loader2, Sparkles } from "lucide-react";
import { errText, parseLink, uploadFile } from "../api";
import type { TaskCreated } from "../types";
import { cn } from "../lib/utils";
import { useToast } from "./Toast";

type FileAccept = Record<string, string[]>;

const MAX_SIZE = 200 * 1024 * 1024;

const ACCEPTS: Record<"image" | "video", FileAccept> = {
  image: { "image/*": [".png", ".jpg", ".jpeg", ".webp", ".bmp"] },
  video: { "video/*": [".mp4", ".mov", ".m4v", ".webm"] },
};

const PLATFORMS = [
  { name: "小红书", match: /xhslink|xiaohongshu/i, cls: "text-rose-300 border-rose-400/25 bg-rose-400/10" },
  { name: "抖音", match: /douyin|iesdouyin/i, cls: "text-cyan-300 border-cyan-400/25 bg-cyan-400/10" },
  { name: "TikTok", match: /tiktok|vm\.tiktok/i, cls: "text-fuchsia-300 border-fuchsia-400/25 bg-fuchsia-400/10" },
];

function detectPlatform(url: string) {
  const hit = PLATFORMS.find((p) => p.match.test(url));
  return hit ?? null;
}

interface Props {
  mediaType: "image" | "video";
  onTask: (t: TaskCreated) => void;
}

export default function ImportPanel({ mediaType, onTask }: Props) {
  const toast = useToast();
  const [uploading, setUploading] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [link, setLink] = useState("");

  const isImage = mediaType === "image";

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    multiple: false,
    accept: ACCEPTS[mediaType],
    maxSize: MAX_SIZE,
    onDrop: async (files) => {
      const f = files[0];
      if (!f) return;
      setUploading(true);
      try {
        const created = await uploadFile(f, mediaType);
        onTask(created);
      } catch (e) {
        toast("error", `上传失败：${errText(e)}`);
      } finally {
        setUploading(false);
      }
    },
    onDropRejected: (rejections) => {
      const code = rejections[0]?.errors[0]?.code;
      if (code === "file-too-large") toast("error", "文件超过 200MB 限制");
      else toast("error", `不支持的${isImage ? "图片" : "视频"}格式`);
    },
  });

  const doParse = async () => {
    const url = link.trim();
    if (!url) {
      toast("info", "请先粘贴分享链接");
      return;
    }
    setParsing(true);
    try {
      const created = await parseLink(url);
      onTask(created);
    } catch (e) {
      toast("error", `解析失败：${errText(e)}`);
    } finally {
      setParsing(false);
    }
  };

  const platform = detectPlatform(link);

  return (
    <div className="glass-card p-6 md:p-8">
      {/* 拖拽上传区 */}
      <div
        {...getRootProps()}
        className={cn(
          "group relative cursor-pointer overflow-hidden rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-all duration-300",
          isDragActive
            ? "border-violet-400 bg-violet-500/10 shadow-[0_0_40px_-8px_rgba(139,92,246,0.45)]"
            : "border-white/15 bg-white/[0.02] hover:border-violet-400/60 hover:bg-violet-500/5",
        )}
      >
        <input {...getInputProps()} />
        <motion.div
          animate={{ y: isDragActive ? -6 : 0 }}
          className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500 to-fuchsia-500 shadow-lg shadow-violet-500/30"
        >
          {uploading ? (
            <Loader2 className="h-8 w-8 animate-spin text-white" />
          ) : isImage ? (
            <ImageIcon className="h-8 w-8 text-white" />
          ) : (
            <Film className="h-8 w-8 text-white" />
          )}
        </motion.div>
        <p className="text-base font-medium text-slate-100">
          {uploading
            ? "正在上传…"
            : isDragActive
              ? "松开即可上传"
              : `点击选择或拖拽${isImage ? "图片" : "视频"}到这里`}
        </p>
        <p className="mt-2 text-xs text-slate-500">
          {isImage
            ? "支持 PNG / JPG / JPEG / WEBP / BMP"
            : "支持 MP4 / MOV / M4V / WEBM"}{" "}
          · 最大 200MB
        </p>
      </div>

      {/* 分隔线 */}
      <div className="my-7 flex items-center gap-4">
        <span className="h-px flex-1 bg-gradient-to-r from-transparent to-white/10" />
        <span className="text-xs text-slate-500">或通过分享链接导入</span>
        <span className="h-px flex-1 bg-gradient-to-l from-transparent to-white/10" />
      </div>

      {/* 链接输入 */}
      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Link2 className="pointer-events-none absolute left-3.5 top-1/2 h-4.5 w-4.5 -translate-y-1/2 text-slate-500" />
          <input
            value={link}
            onChange={(e) => setLink(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !parsing && doParse()}
            placeholder="粘贴小红书 / 抖音 / TikTok 分享链接"
            spellCheck={false}
            className="w-full rounded-xl border border-white/10 bg-white/[0.04] py-3 pl-10 pr-4 text-sm text-slate-100 outline-none transition-all placeholder:text-slate-600 focus:border-violet-400/60 focus:bg-violet-500/[0.06] focus:ring-2 focus:ring-violet-500/20"
          />
        </div>
        <button
          onClick={doParse}
          disabled={parsing || !link.trim()}
          className={cn(
            "flex items-center justify-center gap-2 rounded-xl px-6 py-3 text-sm font-medium transition-all",
            parsing || !link.trim()
              ? "cursor-not-allowed bg-white/5 text-slate-500"
              : "bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white shadow-lg shadow-fuchsia-500/25 hover:brightness-110 active:scale-[0.98]",
          )}
        >
          {parsing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {parsing ? "解析下载中…" : "解析链接"}
        </button>
      </div>

      {/* 平台提示 */}
      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        {platform ? (
          <span
            className={cn(
              "rounded-full border px-2.5 py-1 font-medium",
              platform.cls,
            )}
          >
            已识别：{platform.name}链接
          </span>
        ) : (
          <>
            <span>支持：</span>
            {PLATFORMS.map((p) => (
              <span
                key={p.name}
                className={cn(
                  "rounded-full border px-2.5 py-1 font-medium",
                  p.cls,
                )}
              >
                {p.name}
              </span>
            ))}
          </>
        )}
        <span className="ml-auto hidden sm:block">
          视频下载可能需要数十秒，请耐心等待
        </span>
      </div>
    </div>
  );
}
