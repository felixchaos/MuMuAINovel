/**
 * 后台任务服务 - 轮询任务进度，替代SSE
 */

const API_BASE = '/api/tasks';

export interface TaskStatus {
  id: string;
  task_type: string;
  project_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number; // 0-100
  status_message: string | null;
  progress_details: {
    stage: string;
    message?: string;
    current_chars?: number;
    retry_count?: number;
    queue_size?: number;
  } | null;
  error_message: string | null;
  task_result: Record<string, unknown> | null;
  retry_count: number;
  cancel_requested: boolean;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string | null;
}

export interface TaskListResponse {
  items: TaskStatus[];
}

/**
 * 批量生成任务状态
 */
export interface BatchTaskStatus {
  id: string;
  project_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  total_chapters: number;
  completed_chapters: number;
  current_chapter_number: number | null;
  error_message: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

/**
 * 查询任务状态
 */
export async function getTaskStatus(taskId: string): Promise<TaskStatus> {
  const response = await fetch(`${API_BASE}/${taskId}`);
  if (!response.ok) {
    throw new Error(`查询任务状态失败: ${response.statusText}`);
  }
  return response.json();
}

/**
 * 获取项目的任务列表
 */
export async function getProjectTasks(
  projectId: string,
  taskType?: string,
  limit: number = 20
): Promise<TaskListResponse> {
  const params = new URLSearchParams({ project_id: projectId, limit: String(limit) });
  if (taskType) params.set('task_type', taskType);
  const response = await fetch(`${API_BASE}?${params}`);
  if (!response.ok) {
    throw new Error(`获取任务列表失败: ${response.statusText}`);
  }
  return response.json();
}

/**
 * 获取项目活跃的批量生成任务
 */
export async function getActiveBatchTasks(projectId: string): Promise<BatchTaskStatus[]> {
  const response = await fetch(`/api/chapters/project/${projectId}/batch-generate/active`);
  if (!response.ok) {
    throw new Error(`获取批量生成任务失败: ${response.statusText}`);
  }
  const data = await response.json();
  // API 返回单个任务或空，统一转为数组
  return data ? [data] : [];
}

/**
 * 取消批量生成任务
 */
export async function cancelBatchTask(batchId: string): Promise<void> {
  const response = await fetch(`/api/chapters/batch-generate/${batchId}/cancel`, { method: 'POST' });
  if (!response.ok) {
    throw new Error(`取消批量生成任务失败: ${response.statusText}`);
  }
}

/**
 * 取消任务
 */
export async function cancelTask(taskId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/${taskId}/cancel`, { method: 'POST' });
  if (!response.ok) {
    throw new Error(`取消任务失败: ${response.statusText}`);
  }
}

/**
 * 清理项目已结束的任务记录
 */
export async function clearProjectTasks(projectId: string): Promise<{ deleted_count: number }> {
  const response = await fetch(`${API_BASE}/project/${projectId}/clear`, { method: 'DELETE' });
  if (!response.ok) {
    throw new Error(`清理任务记录失败: ${response.statusText}`);
  }
  return response.json();
}

/**
 * 删除任务记录
 */
export async function deleteTask(taskId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/${taskId}`, { method: 'DELETE' });
  if (!response.ok) {
    throw new Error(`删除任务失败: ${response.statusText}`);
  }
}

export type TaskProgressCallback = (status: TaskStatus) => void;
export type TaskCompleteCallback = (result: TaskStatus) => void;
export type TaskErrorCallback = (error: string, status: TaskStatus) => void;

/**
 * 轮询任务直到完成
 * 
 * @param taskId 任务ID
 * @param onProgress 进度回调
 * @param onComplete 完成回调
 * @param onError 错误回调
 * @param intervalMs 轮询间隔（毫秒），默认2000
 * @returns 取消轮询的函数
 */
export function pollTaskUntilComplete(
  taskId: string,
  onProgress: TaskProgressCallback,
  onComplete: TaskCompleteCallback,
  onError: TaskErrorCallback,
  intervalMs: number = 2000
): () => void {
  let cancelled = false;
  let timerId: ReturnType<typeof setTimeout>;

  const poll = async () => {
    if (cancelled) return;

    try {
      const status = await getTaskStatus(taskId);

      if (cancelled) return;

      onProgress(status);

      if (status.status === 'completed') {
        onComplete(status);
        return;
      }

      if (status.status === 'failed') {
        onError(status.error_message || '任务失败', status);
        return;
      }

      if (status.status === 'cancelled') {
        onError('任务已取消', status);
        return;
      }

      // 继续轮询（运行中时加快轮询频率）
      const nextInterval = status.status === 'running' ? intervalMs : intervalMs * 2;
      timerId = setTimeout(poll, nextInterval);
    } catch (err) {
      if (!cancelled) {
        onError(err instanceof Error ? err.message : '查询任务状态失败', {} as TaskStatus);
      }
    }
  };

  // 立即开始第一次轮询
  timerId = setTimeout(poll, 0);

  // 返回取消函数
  return () => {
    cancelled = true;
    clearTimeout(timerId);
  };
}

/**
 * 请求后台生成大纲并轮询进度
 * 
 * @param data 请求参数（同原来的generate-stream）
 * @param onProgress 进度回调
 * @param onComplete 完成回调
 * @param onError 错误回调
 * @returns 取消函数（同时取消轮询和后台任务）
 */
export async function generateOutlineBackground(
  data: unknown,
  onProgress: TaskProgressCallback,
  onComplete: TaskCompleteCallback,
  onError: TaskErrorCallback
): Promise<() => void> {
  // 1. 创建后台任务
  const response = await fetch('/api/outlines/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    onError(err.detail || '创建任务失败', {} as TaskStatus);
    return () => {};
  }

  const { task_id } = await response.json();

  // 2. 开始轮询
  const cancelPolling = pollTaskUntilComplete(task_id, onProgress, onComplete, onError);

  // 3. 返回统一的取消函数（取消轮询 + 取消后台任务）
  return () => {
    cancelPolling();
    cancelTask(task_id).catch(() => {});
  };
}

/**
 * 请求后台生成章节内容并轮询进度
 * 关闭浏览器不影响生成，生成完成后内容自动保存到数据库
 */
export async function generateChapterBackground(
  chapterId: string,
  options: {
    style_id?: number | null;
    target_word_count?: number;
    model?: string | null;
    narrative_perspective?: string | null;
    enable_mcp?: boolean;
  },
  onProgress: TaskProgressCallback,
  onComplete: TaskCompleteCallback,
  onError: TaskErrorCallback
): Promise<() => void> {
  const response = await fetch(`/api/chapters/${chapterId}/generate-background`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    onError(err.detail || '创建章节生成任务失败', {} as TaskStatus);
    return () => {};
  }

  const { task_id } = await response.json();
  const cancelPolling = pollTaskUntilComplete(task_id, onProgress, onComplete, onError);

  return () => {
    cancelPolling();
    cancelTask(task_id).catch(() => {});
  };
}
