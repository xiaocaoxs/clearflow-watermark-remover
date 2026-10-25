/** 与后端 pipeline.Task.to_dict() 对应的任务状态结构 */

export interface Region {
  x: number;
  y: number;
  w: number;
  h: number;
  conf: number;
}

export interface Track {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  t0: number;
  t1: number;
  hits: number;
}

export interface TaskMeta {
  filename?: string;
  source?: string;
  platform?: string;
  title?: string;
  width?: number;
  height?: number;
  duration?: number;
  detected_count?: number;
  detected_tracks?: number;
  watermark_found?: boolean;
}

export interface TaskInfo {
  task_id: string;
  media_type: "image" | "video";
  status: "uploaded" | "detecting" | "processing" | "done" | "failed";
  stage: string;
  progress: number;
  regions: Region[];
  tracks: Track[];
  meta: TaskMeta;
  error: string;
  has_result: boolean;
  input_name: string;
  output_name: string;
  detect_preview: string;
}

export interface TaskCreated {
  task_id: string;
  media_type: "image" | "video";
  platform?: string;
  title?: string;
  filename?: string;
}
