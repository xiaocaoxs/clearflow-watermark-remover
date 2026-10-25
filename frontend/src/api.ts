import axios from "axios";
import type { TaskCreated, TaskInfo } from "./types";

const http = axios.create({ baseURL: "/", timeout: 600_000 });

/** 本地文件上传 */
export async function uploadFile(
  file: File,
  mediaType: "image" | "video",
): Promise<TaskCreated> {
  const form = new FormData();
  form.append("file", file);
  form.append("media_type", mediaType);
  const { data } = await http.post<
    { task_id: string; media_type: "image" | "video" } & Partial<TaskCreated>
  >("/api/upload", form);
  return { ...data, filename: file.name };
}

/** 解析分享链接（小红书 / 抖音 / TikTok），成功即已代理下载完成 */
export async function parseLink(url: string): Promise<TaskCreated> {
  const { data } = await http.post<
    { task_id: string; media_type: "image" | "video" } & Partial<TaskCreated>
  >("/api/parse-link", { url });
  return data as TaskCreated;
}

/** 触发水印检测 + 去除（后台异步执行，前端轮询状态） */
export async function startProcess(taskId: string): Promise<void> {
  await http.post("/api/process", { task_id: taskId });
}

/** 轮询任务状态 */
export async function getTask(taskId: string): Promise<TaskInfo> {
  const { data } = await http.get<TaskInfo>(`/api/task/${taskId}`);
  return data;
}

/* ---------- 媒体地址（走静态挂载，支持视频 Range 拖动） ---------- */

export const originalUrl = (t: TaskInfo) =>
  t.input_name ? `/uploads/${encodeURIComponent(t.input_name)}` : "";

export const resultUrl = (t: TaskInfo) =>
  t.output_name ? `/files/${encodeURIComponent(t.output_name)}` : "";

export const detectPreviewUrl = (t: TaskInfo) =>
  t.detect_preview ? `/files/${encodeURIComponent(t.detect_preview)}` : "";

/* ---------- 错误信息提取 ---------- */

export function errText(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const d = e.response?.data as { detail?: string } | undefined;
    if (d?.detail) return String(d.detail);
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}
