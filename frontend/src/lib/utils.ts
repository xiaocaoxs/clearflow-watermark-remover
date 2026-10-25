import { clsx, type ClassValue } from "clsx";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function fmtTime(t: number): string {
  if (!isFinite(t) || t < 0) return "0:00";
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

const PLATFORM_NAMES: Record<string, string> = {
  xiaohongshu: "小红书",
  douyin: "抖音",
  tiktok: "TikTok",
};

export function platformName(p?: string): string {
  if (!p) return "";
  return PLATFORM_NAMES[p] ?? p;
}
