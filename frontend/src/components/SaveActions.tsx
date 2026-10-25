import { useState } from "react";
import { Download, Loader2, Share2 } from "lucide-react";
import type { TaskInfo } from "../types";
import { resultUrl } from "../api";
import { cn } from "../lib/utils";
import { useToast } from "./Toast";

interface Props {
  task: TaskInfo;
}

function buildFilename(task: TaskInfo): string {
  const ext =
    task.media_type === "video"
      ? "mp4"
      : (task.input_name.split(".").pop() || "jpg").toLowerCase();
  const raw =
    (task.meta.title || task.meta.filename || "media").replace(
      /[\\/:*?"<>|\n]/g,
      "",
    );
  const name = raw.slice(0, 24).trim() || "media";
  return `无水印_${name}.${ext}`;
}

async function triggerDownload(url: string, filename: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("获取文件失败");
  const blob = await res.blob();
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(objUrl), 10_000);
  return blob;
}

export default function SaveActions({ task }: Props) {
  const toast = useToast();
  const [busy, setBusy] = useState<"download" | "share" | null>(null);
  const url = resultUrl(task);
  const filename = buildFilename(task);

  const download = async () => {
    setBusy("download");
    try {
      await triggerDownload(url, filename);
      toast("success", "已开始下载到本地");
    } catch {
      toast("error", "下载失败，请重试");
    } finally {
      setBusy(null);
    }
  };

  const saveToAlbum = async () => {
    setBusy("share");
    try {
      const blob = await fetch(url).then((r) => {
        if (!r.ok) throw new Error("获取文件失败");
        return r.blob();
      });
      const type =
        blob.type ||
        (task.media_type === "video" ? "video/mp4" : "image/jpeg");
      const file = new File([blob], filename, { type });
      const nav = navigator as Navigator & {
        canShare?: (data: ShareData) => boolean;
      };
      if (typeof nav.share === "function" && nav.canShare?.({ files: [file] })) {
        await nav.share({ files: [file], title: filename });
        toast("success", "已调起系统分享，选择「存储到相册」即可保存");
      } else {
        await triggerDownload(url, filename);
        toast("info", "当前浏览器不支持保存到相册，已改为下载到本地");
      }
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      toast("error", "保存失败，请重试");
    } finally {
      setBusy(null);
    }
  };

  const busyNow = busy !== null;

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:justify-center">
      <button
        onClick={download}
        disabled={busyNow}
        className={cn(
          "flex items-center justify-center gap-2 rounded-xl px-7 py-3.5 text-sm font-semibold transition-all",
          busyNow
            ? "cursor-wait opacity-60"
            : "bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white shadow-lg shadow-fuchsia-500/30 hover:brightness-110 active:scale-[0.98]",
        )}
      >
        {busy === "download" ? (
          <Loader2 className="h-4.5 w-4.5 animate-spin" />
        ) : (
          <Download className="h-4.5 w-4.5" />
        )}
        下载到本地
      </button>
      <button
        onClick={saveToAlbum}
        disabled={busyNow}
        className={cn(
          "flex items-center justify-center gap-2 rounded-xl border px-7 py-3.5 text-sm font-semibold transition-all",
          busyNow
            ? "cursor-wait opacity-60"
            : "border-emerald-400/30 bg-emerald-500/10 text-emerald-300 hover:border-emerald-400/60 hover:bg-emerald-500/15 active:scale-[0.98]",
        )}
      >
        {busy === "share" ? (
          <Loader2 className="h-4.5 w-4.5 animate-spin" />
        ) : (
          <Share2 className="h-4.5 w-4.5" />
        )}
        保存到相册
      </button>
    </div>
  );
}
