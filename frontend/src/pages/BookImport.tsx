import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  Empty,
  Input,
  InputNumber,
  List,
  message,
  Modal,
  Popconfirm,
  Progress,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Steps,
  Tag,
  Typography,
  Upload,
  theme,
} from 'antd';
import type { UploadFile } from 'antd/es/upload/interface';
import { InboxOutlined, PlayCircleOutlined, ReloadOutlined, StopOutlined, WarningOutlined, RedoOutlined, HighlightOutlined } from '@ant-design/icons';
import { bookImportApi, polishApi } from '../services/api';
import type {
  BookImportApplyPayload,
  BookImportEntityCandidate,
  BookImportExtractMode,
  BookImportPreview,
  BookImportProjectSuggestion,
  BookImportSetupMode,
  BookImportStepFailure,
  BookImportTask,
} from '../types';

const { Text, Title } = Typography;
const { Dragger } = Upload;
const { TextArea } = Input;

const BOOK_IMPORT_CACHE_KEY = 'book_import_page_cache_v1';

type BookImportPageCache = {
  taskId: string | null;
  taskStatus: BookImportTask | null;
  preview: BookImportPreview | null;
  applyProgress: number;
  applyMessage: string;
  applyError: string | null;
  isApplyComplete: boolean;
  extractMode: BookImportExtractMode;
  tailChapterCount: number;
  setupMode: BookImportSetupMode;
  postImportGeneration: 'auto' | 'manual';
  cachedAt: number;
};

function loadBookImportCache(): BookImportPageCache | null {
  try {
    const raw = sessionStorage.getItem(BOOK_IMPORT_CACHE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as BookImportPageCache;
  } catch (error) {
    console.warn('读取拆书页面缓存失败:', error);
    return null;
  }
}

function saveBookImportCache(cache: BookImportPageCache) {
  try {
    sessionStorage.setItem(BOOK_IMPORT_CACHE_KEY, JSON.stringify(cache));
  } catch (error) {
    const isQuotaExceeded =
      error instanceof DOMException &&
      (error.name === 'QuotaExceededError' || error.name === 'NS_ERROR_DOM_QUOTA_REACHED');

    if (isQuotaExceeded) {
      // 发生容量溢出时降级为轻量缓存（不保存预览正文），避免持续报错
      try {
        const lightweightCache: BookImportPageCache = {
          ...cache,
          preview: null,
        };
        sessionStorage.setItem(BOOK_IMPORT_CACHE_KEY, JSON.stringify(lightweightCache));
        return;
      } catch (fallbackError) {
        console.warn('写入轻量拆书页面缓存失败:', fallbackError);
        try {
          sessionStorage.removeItem(BOOK_IMPORT_CACHE_KEY);
        } catch {
          // ignore
        }
      }
    }

    console.warn('写入拆书页面缓存失败:', error);
  }
}

function clearBookImportCache() {
  try {
    sessionStorage.removeItem(BOOK_IMPORT_CACHE_KEY);
  } catch (error) {
    console.warn('清理拆书页面缓存失败:', error);
  }
}

function isNotFoundError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false;
  const maybeError = error as { response?: { status?: number } };
  return maybeError.response?.status === 404;
}

type ImportSuggestionField = keyof BookImportProjectSuggestion;

function bookImportEntityCandidateKey(item: BookImportEntityCandidate): string {
  return `${item.entity_type}:${item.name}`;
}

function formatApproxTokens(value?: number): string {
  const count = Math.max(0, Math.round(value || 0));
  if (count >= 10000) return `${(count / 10000).toFixed(1)}万`;
  return count.toLocaleString();
}

function findPreviewSplitPosition(content: string, marker: string): number {
  const text = content || '';
  const trimmedMarker = marker.trim();
  if (trimmedMarker) {
    const markerIndex = text.indexOf(trimmedMarker);
    return markerIndex;
  }

  const midpoint = Math.floor(text.length / 2);
  const paragraphBreaks = [...text.matchAll(/\n\s*\n/g)].map((match) => match.index ?? -1).filter((idx) => idx > 0);
  if (paragraphBreaks.length > 0) {
    return paragraphBreaks.reduce((best, current) =>
      Math.abs(current - midpoint) < Math.abs(best - midpoint) ? current : best
    );
  }

  const sentenceBreaks = [...text.matchAll(/[。！？!?]\s*/g)]
    .map((match) => (match.index ?? -1) + match[0].length)
    .filter((idx) => idx > 0);
  if (sentenceBreaks.length > 0) {
    return sentenceBreaks.reduce((best, current) =>
      Math.abs(current - midpoint) < Math.abs(best - midpoint) ? current : best
    );
  }

  return midpoint;
}

const importSuggestionFieldLabels: Partial<Record<ImportSuggestionField, string>> = {
  title: '标题',
  genre: '类型',
  theme: '主题',
  description: '简介',
  world_time_period: '时间背景',
  world_location: '地理位置',
  world_atmosphere: '氛围基调',
  world_rules: '世界规则',
};

function buildImportSuggestionContext(suggestion: BookImportProjectSuggestion, activeLabel: string) {
  const lines = Object.entries(importSuggestionFieldLabels)
    .map(([field, label]) => {
      const value = suggestion[field as ImportSuggestionField];
      const text = value === undefined || value === null ? '' : String(value).trim();
      return text ? `${label}：${text}` : '';
    })
    .filter(Boolean);

  return lines.length > 0
    ? `当前拆书项目信息：\n${lines.join('\n')}\n\n需要处理的字段：${activeLabel}`
    : `需要为拆书项目生成或润色字段：${activeLabel}`;
}

function projectSuggestionPatch(
  field: ImportSuggestionField,
  value: string,
): Partial<BookImportProjectSuggestion> {
  if (field === 'target_words') {
    return { target_words: Number(value || 100000) };
  }
  return { [field]: value } as Partial<BookImportProjectSuggestion>;
}

export default function BookImport() {
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const isMobile = window.innerWidth <= 768;
  const [file, setFile] = useState<File | null>(null);
  const [extractMode, setExtractMode] = useState<BookImportExtractMode>('tail');
  const [tailChapterCount, setTailChapterCount] = useState(10);
  const [setupMode, setSetupMode] = useState<BookImportSetupMode>('auto');
  const [postImportGeneration, setPostImportGeneration] = useState<'auto' | 'manual'>('auto');
  const [modal, contextHolder] = Modal.useModal();

  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<BookImportTask | null>(null);
  const [preview, setPreview] = useState<BookImportPreview | null>(null);
  const [selectedEntityCandidateKeys, setSelectedEntityCandidateKeys] = useState<string[]>([]);

  const [creatingTask, setCreatingTask] = useState(false);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyProgress, setApplyProgress] = useState(0);
  const [applyMessage, setApplyMessage] = useState('');
  const [applyError, setApplyError] = useState<string | null>(null);
  const [isApplyComplete, setIsApplyComplete] = useState(false);
  const [cacheReady, setCacheReady] = useState(false);

  // 步骤级失败和重试相关状态
  const [failedSteps, setFailedSteps] = useState<BookImportStepFailure[]>([]);
  const [retrying, setRetrying] = useState(false);
  const [retryProgress, setRetryProgress] = useState(0);
  const [retryMessage, setRetryMessage] = useState('');
  const importedProjectId = useRef<string | null>(null);

  const isTaskTerminal = useMemo(() => {
    return !!taskStatus && ['completed', 'failed', 'cancelled'].includes(taskStatus.status);
  }, [taskStatus]);

  const currentStep = useMemo(() => {
    if (!taskId) return 0;
    if (taskStatus && ['pending', 'running'].includes(taskStatus.status)) return 1;
    if (applying || isApplyComplete) return 3; // 新增生成导入步骤
    if (preview) return 2;
    return 1;
  }, [taskId, taskStatus, preview, applying, isApplyComplete]);

  const canRestart = useMemo(() => {
    return Boolean(
      file ||
      taskId ||
      taskStatus ||
      preview ||
      applyProgress > 0 ||
      applyMessage ||
      applyError ||
      isApplyComplete ||
      failedSteps.length > 0 ||
      retrying
    );
  }, [
    file,
    taskId,
    taskStatus,
    preview,
    applyProgress,
    applyMessage,
    applyError,
    isApplyComplete,
    failedSteps,
    retrying,
  ]);

  useEffect(() => {
    if (!preview?.entity_candidates?.length) {
      setSelectedEntityCandidateKeys([]);
      return;
    }

    setSelectedEntityCandidateKeys(
      preview.entity_candidates
        .filter((item) =>
          (item.entity_type === 'character' || item.entity_type === 'organization') &&
          (item.confidence ?? 0.6) >= 0.45
        )
        .slice(0, 40)
        .map(bookImportEntityCandidateKey)
    );
  }, [preview?.task_id]);

  const selectedEntityCandidateKeySet = useMemo(
    () => new Set(selectedEntityCandidateKeys),
    [selectedEntityCandidateKeys]
  );

  const selectedEntityCandidates = useMemo(() => {
    if (!preview?.entity_candidates?.length) return [];
    return preview.entity_candidates.filter((item) =>
      selectedEntityCandidateKeySet.has(bookImportEntityCandidateKey(item))
    );
  }, [preview?.entity_candidates, selectedEntityCandidateKeySet]);

  const normalizedTailChapterCount = useMemo(
    () => Math.max(5, Math.ceil(tailChapterCount / 5) * 5),
    [tailChapterCount]
  );
  const effectiveExtractMode = useMemo<BookImportExtractMode>(
    () => (normalizedTailChapterCount > 50 ? 'full' : extractMode),
    [extractMode, normalizedTailChapterCount]
  );
  const rangeLocked = Boolean(taskId || taskStatus || preview || creatingTask || applying || retrying);

  const stepItems = [
    { title: '上传文件' },
    { title: '解析中' },
    { title: '预览修改' },
    { title: '生成导入' },
  ];
  const currentStepText = stepItems[currentStep]?.title || '上传文件';

  useEffect(() => {
    const cache = loadBookImportCache();
    if (cache) {
      const cacheAgeMs = typeof cache.cachedAt === 'number'
        ? Date.now() - cache.cachedAt
        : Number.POSITIVE_INFINITY;

      // 超过6小时的缓存直接视为失效，避免后端重启后继续使用旧taskId
      if (cacheAgeMs > 6 * 60 * 60 * 1000) {
        clearBookImportCache();
      } else {
        setTaskId(cache.taskId);
        setTaskStatus(cache.taskStatus);
        setPreview(cache.preview);
        setApplyProgress(cache.applyProgress);
        setApplyError(cache.applyError);
        setIsApplyComplete(cache.isApplyComplete);
        setExtractMode(cache.extractMode ?? 'tail');
        setTailChapterCount(cache.tailChapterCount ?? 10);
        setSetupMode(cache.setupMode ?? 'auto');
        setPostImportGeneration(cache.postImportGeneration ?? 'auto');
        setApplyMessage(
          cache.applyMessage || (cache.applyProgress > 0 && !cache.isApplyComplete
            ? '已恢复页面缓存，请重新点击“确认导入”继续。'
            : '')
        );
        message.info('已恢复拆书导入页面缓存');
      }
    }
    setCacheReady(true);
  }, []);

  useEffect(() => {
    if (!cacheReady) return;

    // 导入完成后必须清理缓存，避免后续回到页面时恢复到旧任务状态
    if (isApplyComplete) {
      clearBookImportCache();
      return;
    }

    const hasCacheData = Boolean(
      taskId ||
      taskStatus ||
      preview ||
      applyError ||
      applyProgress > 0 ||
      applyMessage
    );

    if (!hasCacheData) {
      clearBookImportCache();
      return;
    }

    saveBookImportCache({
      taskId,
      taskStatus,
      // preview 含完整章节正文，体积大，容易触发 sessionStorage 配额限制
      // 页面恢复时可根据 taskId + taskStatus 重新拉取 preview
      preview: null,
      applyProgress,
      applyMessage,
      applyError,
      isApplyComplete,
      extractMode,
      tailChapterCount,
      setupMode,
      postImportGeneration,
      cachedAt: Date.now(),
    });
  }, [
    cacheReady,
    taskId,
    taskStatus,
    preview,
    applyProgress,
    applyMessage,
    applyError,
    isApplyComplete,
    extractMode,
    tailChapterCount,
    setupMode,
    postImportGeneration,
  ]);

  useEffect(() => {
    if (!taskId) return;
    if (isTaskTerminal) return;

    const timer = setInterval(async () => {
      try {
        const status = await bookImportApi.getTaskStatus(taskId);
        setTaskStatus(status);
      } catch (error) {
        console.error('轮询任务状态失败:', error);
        if (isNotFoundError(error)) {
          clearBookImportCache();
          setTaskId(null);
          setTaskStatus(null);
          setPreview(null);
          setApplyProgress(0);
          setApplyMessage('');
          setApplyError(null);
          setIsApplyComplete(false);
          message.warning('拆书任务已失效（可能因服务重启），请重新上传TXT并开始解析');
        }
      }
    }, 1500);

    return () => clearInterval(timer);
  }, [taskId, isTaskTerminal]);

  useEffect(() => {
    const fetchPreview = async () => {
      if (!taskId || !taskStatus) return;
      if (taskStatus.status !== 'completed' || preview) return;

      try {
        setLoadingPreview(true);
        const data = await bookImportApi.getPreview(taskId);
        setPreview(data);
      } catch (error) {
        console.error('获取预览失败:', error);
        if (isNotFoundError(error)) {
          clearBookImportCache();
          setTaskId(null);
          setTaskStatus(null);
          setPreview(null);
          setApplyProgress(0);
          setApplyMessage('');
          setApplyError(null);
          setIsApplyComplete(false);
          message.warning('拆书任务预览不存在（可能因服务重启），已清空缓存，请重新上传TXT');
        } else {
          message.error('获取预览失败');
        }
      } finally {
        setLoadingPreview(false);
      }
    };

    fetchPreview();
  }, [taskId, taskStatus, preview]);

  const startTask = async () => {
    if (!file) {
      message.warning('请先选择 TXT 文件');
      return;
    }

    try {
      setCreatingTask(true);
      setPreview(null);
      setTaskStatus(null);

      setExtractMode(effectiveExtractMode);
      setTailChapterCount(normalizedTailChapterCount);

      const response = await bookImportApi.createTask({
        file,
        extract_mode: effectiveExtractMode,
        tail_chapter_count: normalizedTailChapterCount,
        setup_mode: setupMode,
      });

      setTaskId(response.task_id);
      message.success('拆书任务已创建');
    } catch (error) {
      console.error('创建任务失败:', error);
      message.error('创建拆书任务失败');
    } finally {
      setCreatingTask(false);
    }
  };

  const refreshStatus = async () => {
    if (!taskId) return;
    try {
      const status = await bookImportApi.getTaskStatus(taskId);
      setTaskStatus(status);
    } catch (error) {
      console.error('刷新状态失败:', error);
      if (isNotFoundError(error)) {
        clearBookImportCache();
        setTaskId(null);
        setTaskStatus(null);
        setPreview(null);
        setApplyProgress(0);
        setApplyMessage('');
        setApplyError(null);
        setIsApplyComplete(false);
        message.warning('任务不存在，已清空本地缓存，请重新创建拆书任务');
      }
    }
  };

  const cancelTask = async () => {
    if (!taskId) return;
    try {
      await bookImportApi.cancelTask(taskId);
      message.success('任务已取消');
      await refreshStatus();
    } catch (error) {
      console.error('取消任务失败:', error);
      message.error('取消任务失败');
    }
  };

  const applyImport = async () => {
    if (!taskId || !preview) return;

    const payload: BookImportApplyPayload = {
      project_suggestion: preview.project_suggestion,
      chapters: preview.chapters,
      outlines: preview.outlines,
      entity_candidates: selectedEntityCandidates,
      import_mode: 'append',
      post_import_generation: postImportGeneration,
    };

    try {
      setApplying(true);
      setApplyProgress(0);
      setApplyMessage('准备导入...');
      setApplyError(null);
      setIsApplyComplete(false);
      setFailedSteps([]);

      await bookImportApi.applyImportStream(
        taskId,
        payload,
        {
          onProgress: (msg, prog, status) => {
            // 检查是否是步骤失败的特殊消息
            if (status === 'step_failures') {
              try {
                const parsed = JSON.parse(msg);
                if (parsed.failed_steps && Array.isArray(parsed.failed_steps)) {
                  setFailedSteps(parsed.failed_steps as BookImportStepFailure[]);
                }
              } catch {
                // 不是JSON，忽略
              }
              return;
            }
            setApplyProgress(prog);
            setApplyMessage(msg);
          },
          onResult: (result) => {
            importedProjectId.current = result.project_id;
            const generatedCareers = result.statistics?.generated_careers ?? 0;
            const generatedEntities = result.statistics?.generated_entities ?? 0;
            const successText = postImportGeneration === 'manual'
              ? '导入成功：已跳过AI生成，可手动完善设定'
              : `导入成功：已生成职业${generatedCareers}个，角色/组织${generatedEntities}个`;

            // 检查最终是否有失败步骤
            setIsApplyComplete(true);

            // 如果没有失败步骤才自动跳转
            // 注意：这里需要延迟一帧来等待 failedSteps 的更新
            setTimeout(() => {
              setFailedSteps(prev => {
                if (prev.length === 0) {
                  message.success(successText);
                  clearBookImportCache();
                  setTimeout(() => {
                    navigate(`/project/${result.project_id}/chapters`);
                  }, 1000);
                } else {
                  message.warning(`导入完成，但有 ${prev.length} 个生成步骤失败，可点击重试`);
                }
                return prev;
              });
            }, 100);
          },
          onError: (error) => {
            console.error('导入过程发生错误:', error);
            setApplyError(`导入失败: ${error}`);
            message.error(`导入失败: ${error}`);
            setApplying(false);
          },
          onComplete: () => {
            setApplyProgress(100);
            setApplyMessage('导入完成！');
          }
        }
      );
    } catch (error) {
      console.error('确认导入失败:', error);
      setApplyError('确认导入失败，无法连接到服务器');
      message.error('确认导入失败');
      setApplying(false);
    }
  };

  const retryFailedSteps = useCallback(async () => {
    if (!taskId || failedSteps.length === 0) return;

    const stepsToRetry = failedSteps.map(f => f.step_name);

    try {
      setRetrying(true);
      setRetryProgress(0);
      setRetryMessage('正在重试失败的生成步骤...');

      await bookImportApi.retryFailedStepsStream(
        taskId,
        stepsToRetry,
        {
          onProgress: (msg, prog, status) => {
            if (status === 'step_failures') {
              try {
                const parsed = JSON.parse(msg);
                if (parsed.failed_steps && Array.isArray(parsed.failed_steps)) {
                  setFailedSteps(parsed.failed_steps as BookImportStepFailure[]);
                }
              } catch {
                // 不是JSON，忽略
              }
              return;
            }
            setRetryProgress(prog);
            setRetryMessage(msg);
          },
          onResult: (result) => {
            if (result.still_failed && result.still_failed.length > 0) {
              setFailedSteps(result.still_failed);
              message.warning(`重试完成，仍有 ${result.still_failed.length} 个步骤失败`);
            } else {
              setFailedSteps([]);
              message.success('所有步骤重试成功！');
              clearBookImportCache();
              const projectId = result.project_id || importedProjectId.current;
              if (projectId) {
                setTimeout(() => {
                  navigate(`/project/${projectId}/chapters`);
                }, 1000);
              }
            }
          },
          onError: (error) => {
            console.error('重试失败:', error);
            message.error(`重试失败: ${error}`);
          },
          onComplete: () => {
            setRetrying(false);
            setRetryProgress(100);
            setRetryMessage('重试完成');
          }
        }
      );
    } catch (error) {
      console.error('重试请求失败:', error);
      message.error('重试请求失败，无法连接到服务器');
      setRetrying(false);
    }
  }, [taskId, failedSteps, navigate]);

  const skipFailedSteps = useCallback(() => {
    setFailedSteps([]);
    clearBookImportCache();
    const projectId = importedProjectId.current;
    if (projectId) {
      message.info('已跳过失败步骤，正在跳转到项目...');
      navigate(`/project/${projectId}/chapters`);
    }
  }, [navigate]);

  const restartImport = useCallback(() => {
    clearBookImportCache();
    importedProjectId.current = null;

    setFile(null);
    setTaskId(null);
    setTaskStatus(null);
    setPreview(null);

    setCreatingTask(false);
    setLoadingPreview(false);
    setApplying(false);
    setApplyProgress(0);
    setApplyMessage('');
    setApplyError(null);
    setIsApplyComplete(false);

    setFailedSteps([]);
    setRetrying(false);
    setRetryProgress(0);
    setRetryMessage('');
    setExtractMode('tail');
    setTailChapterCount(10);
    setSetupMode('auto');
    setPostImportGeneration('auto');

    message.success('已重新开始，请重新上传 TXT 并解析');
  }, []);

  const updateChapter = (index: number, patch: Partial<BookImportPreview['chapters'][number]>) => {
    setPreview(prev => {
      if (!prev) return prev;
      const next = [...prev.chapters];
      next[index] = { ...next[index], ...patch };
      return { ...prev, chapters: next };
    });
  };

  const mergeChapterWithNext = (index: number) => {
    setPreview(prev => {
      if (!prev || index < 0 || index >= prev.chapters.length - 1) return prev;

      const current = prev.chapters[index];
      const nextChapter = prev.chapters[index + 1];
      const chapters = [...prev.chapters];
      chapters.splice(index, 2, {
        ...current,
        content: [current.content, nextChapter.content].filter(Boolean).join('\n\n'),
        summary: [current.summary, nextChapter.summary].filter(Boolean).join('\n'),
      });

      const normalizedChapters = chapters.map((chapter, chapterIndex) => ({
        ...chapter,
        chapter_number: chapterIndex + 1,
        outline_title: chapter.outline_title || chapter.title,
      }));
      const outlines = prev.outlines
        .filter((_, outlineIndex) => outlineIndex !== index + 1)
        .map((outline, outlineIndex) => ({
          ...outline,
          order_index: outlineIndex + 1,
          title: normalizedChapters[outlineIndex]?.outline_title || outline.title,
        }));

      return { ...prev, chapters: normalizedChapters, outlines };
    });
    message.success('已合并下一章，请检查标题和摘要');
  };

  const splitPreviewChapter = (index: number) => {
    if (!preview?.chapters[index]) return;
    let splitMarker = '';

    modal.confirm({
      title: '拆分章节',
      icon: <WarningOutlined />,
      width: 640,
      centered: true,
      okText: '确认拆分',
      cancelText: '取消',
      content: (
        <Space direction="vertical" style={{ width: '100%', marginTop: 12 }}>
          <Text type="secondary">
            输入新章节开头的一段原文；留空则按最接近中间的段落边界拆分。
          </Text>
          <TextArea
            rows={4}
            placeholder="例如：粘贴下一章开头的第一句话或小节标题"
            onChange={(event) => {
              splitMarker = event.target.value;
            }}
          />
        </Space>
      ),
      onOk: () => {
        const chapter = preview.chapters[index];
        const content = chapter.content || '';
        const splitAt = findPreviewSplitPosition(content, splitMarker);
        if (splitAt <= 0 || splitAt >= content.length - 1) {
          message.error('没有找到合适的拆分位置，请输入更明确的新章节开头');
          return Promise.reject(new Error('invalid split position'));
        }

        setPreview(prev => {
          if (!prev) return prev;
          const target = prev.chapters[index];
          if (!target) return prev;

          const firstContent = (target.content || '').slice(0, splitAt).trim();
          const secondContent = (target.content || '').slice(splitAt).trim();
          if (!firstContent || !secondContent) return prev;

          const chapters = [...prev.chapters];
          chapters.splice(
            index,
            1,
            { ...target, content: firstContent },
            {
              ...target,
              title: `${target.title}（拆分）`,
              content: secondContent,
              summary: '',
              outline_title: `${target.outline_title || target.title}（拆分）`,
            }
          );
          const normalizedChapters = chapters.map((item, chapterIndex) => ({
            ...item,
            chapter_number: chapterIndex + 1,
          }));
          const outlines = [...prev.outlines];
          const currentOutline = outlines[index];
          if (currentOutline) {
            outlines.splice(index + 1, 0, {
              ...currentOutline,
              title: `${currentOutline.title}（拆分）`,
              content: '',
              order_index: index + 2,
              structure: undefined,
            });
          }
          const normalizedOutlines = outlines.map((outline, outlineIndex) => ({
            ...outline,
            order_index: outlineIndex + 1,
          }));

          return { ...prev, chapters: normalizedChapters, outlines: normalizedOutlines };
        });
        message.success('已拆分章节，请检查新章节标题和摘要');
      },
    });
  };

  const updateProjectSuggestion = (patch: Partial<BookImportProjectSuggestion>) => {
    setPreview(prev => prev ? ({
      ...prev,
      project_suggestion: { ...prev.project_suggestion, ...patch },
    }) : prev);
  };

  const runProjectSuggestionAI = async (field: ImportSuggestionField, label: string) => {
    if (!preview) return;

    const suggestion = preview.project_suggestion;
    const currentValue = String(suggestion[field] || '').trim();
    const contextText = buildImportSuggestionContext(suggestion, label);
    const sourceText = currentValue || contextText;
    let instruction = '';

    modal.confirm({
      title: `${label} AI处理要求`,
      icon: <HighlightOutlined />,
      width: 640,
      centered: true,
      okText: currentValue ? '开始润色' : '开始补全',
      cancelText: '取消',
      content: (
        <div style={{ marginTop: 12 }}>
          <div style={{ marginBottom: 12, color: token.colorTextSecondary }}>
            {currentValue
              ? '输入希望 AI 如何润色该字段；留空则只做自然表达优化。'
              : '当前字段为空，AI会参考已填写的拆书项目信息补全。'}
          </div>
          <TextArea
            rows={4}
            placeholder="例如：保持原设定但更清晰；强化时代感；压缩成一句话；不要新增未出现的设定..."
            autoFocus
            onChange={(event) => {
              instruction = event.target.value;
            }}
          />
          <div style={{
            marginTop: 12,
            maxHeight: 120,
            overflowY: 'auto',
            whiteSpace: 'pre-wrap',
            lineHeight: 1.6,
            padding: '8px 10px',
            border: `1px solid ${token.colorBorderSecondary}`,
            borderRadius: token.borderRadius,
            background: token.colorFillQuaternary,
            color: token.colorTextSecondary,
          }}>
            {sourceText}
          </div>
        </div>
      ),
      onOk: async () => {
        const closeLoading = message.loading(`正在处理${label}...`, 0);
        try {
          const defaultInstruction = currentValue
            ? `请润色「${label}」。保留原意和原文设定，不新增无依据内容，不输出解释，只输出处理后的文本。`
            : `请根据拆书项目信息补全「${label}」。不要输出解释、标题或前后缀，只输出可直接填入字段的文本。`;
          const result = await polishApi.polishText({
            original_text: sourceText,
            temperature: currentValue ? 0.65 : 0.8,
            instruction: instruction.trim() || defaultInstruction,
          });
          const aiText = (result.polished_text || '').trim();
          if (!aiText) {
            message.warning('AI结果为空，请稍后重试');
            return;
          }

          modal.confirm({
            title: `${label} AI结果`,
            icon: <HighlightOutlined />,
            width: 720,
            centered: true,
            okText: '应用结果',
            cancelText: currentValue ? '保留原文' : '暂不应用',
            content: (
              <div style={{ marginTop: 12 }}>
                <div style={{ marginBottom: 12, color: token.colorTextSecondary }}>
                  AI结果需要确认后才会写入拆书预览。
                </div>
                <div style={{
                  whiteSpace: 'pre-wrap',
                  lineHeight: 1.6,
                  padding: '8px 10px',
                  border: `1px solid ${token.colorPrimaryBorder}`,
                  borderRadius: token.borderRadius,
                  background: token.colorBgContainer,
                }}>
                  {aiText}
                </div>
              </div>
            ),
            onOk: () => {
              updateProjectSuggestion(projectSuggestionPatch(field, aiText));
              message.success(`${label}已应用AI结果`);
            },
          });
        } catch (error) {
          console.error(`${label} AI处理失败:`, error);
          message.error(`${label} AI处理失败`);
        } finally {
          closeLoading();
        }
      },
    });
  };

  const renderSuggestionLabel = (field: ImportSuggestionField, label: string) => (
    <Space size={6}>
      <Text>{label}</Text>
      <Button
        type="link"
        size="small"
        icon={<HighlightOutlined />}
        style={{ paddingInline: 0 }}
        onClick={() => runProjectSuggestionAI(field, label)}
      >
        AI辅助
      </Button>
    </Space>
  );

  return (
    <div
      style={{
        minHeight: '90vh',
        overflow: 'auto',
        background: `linear-gradient(180deg, ${token.colorBgLayout} 0%, ${token.colorFillSecondary} 100%)`,
        padding: isMobile ? '20px 16px 70px' : '24px 24px 70px',
      }}
    >
      {contextHolder}
      <div style={{ maxWidth: 1400, margin: '0 auto', width: '100%' }}>
        <Card
          variant="borderless"
          style={{
            background: `linear-gradient(135deg, ${token.colorPrimary} 0%, ${token.colorPrimaryHover} 100%)`,
            borderRadius: isMobile ? 16 : 20,
            boxShadow: token.boxShadowSecondary,
            marginBottom: isMobile ? 14 : 16,
            border: 'none',
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          <div style={{ position: 'absolute', top: -48, right: -48, width: 160, height: 160, borderRadius: '50%', background: token.colorWhite, opacity: 0.08, pointerEvents: 'none' }} />
          <div style={{ position: 'absolute', bottom: -40, left: '26%', width: 110, height: 110, borderRadius: '50%', background: token.colorWhite, opacity: 0.05, pointerEvents: 'none' }} />

          <Row align="middle" justify="space-between" gutter={[16, 16]} style={{ position: 'relative', zIndex: 1 }}>
            <Col xs={24} sm={12}>
              <Space direction="vertical" size={4}>
                <Title level={isMobile ? 3 : 2} style={{ margin: 0, color: token.colorWhite, textShadow: `0 2px 4px ${token.colorBgMask}` }}>
                  <InboxOutlined style={{ color: token.colorWhite, opacity: 0.9, marginRight: 8 }} />
                  拆书导入
                </Title>
                <Text style={{ fontSize: isMobile ? 12 : 14, color: token.colorTextLightSolid, opacity: 0.85, marginLeft: isMobile ? 40 : 48 }}>
                  上传TXT并自动解析为章节、预览并导入项目
                </Text>
              </Space>
            </Col>
            <Col xs={24} sm={12}>
              <Space
                size={12}
                style={{
                  width: '100%',
                  display: 'flex',
                  justifyContent: isMobile ? 'flex-start' : 'flex-end',
                }}
              >
                <Tag
                  style={{
                    marginInlineEnd: 0,
                    background: token.colorWhite,
                    border: `1px solid ${token.colorWhite}`,
                    color: token.colorPrimary,
                    fontWeight: 600,
                    borderRadius: 8,
                    paddingInline: 10,
                  }}
                >
                  当前进度：{currentStepText}
                </Tag>
                <Popconfirm
                  title="确认重新开始？"
                  description="将清空当前拆书任务与缓存，并回到上传文件步骤。"
                  onConfirm={restartImport}
                  okText="重新开始"
                  cancelText="取消"
                  disabled={!canRestart}
                >
                  <Button
                    danger
                    type="primary"
                    icon={<ReloadOutlined />}
                    disabled={!canRestart}
                    style={{ boxShadow: '0 6px 16px rgba(0, 0, 0, 0.2)', borderRadius: 10 }}
                  >
                    重新开始
                  </Button>
                </Popconfirm>
              </Space>
            </Col>
          </Row>

          <Card
            variant="borderless"
            style={{
              marginTop: isMobile ? 14 : 18,
              borderRadius: 12,
              background: token.colorBgContainer,
              border: `1px solid ${token.colorBorderSecondary}`,
              boxShadow: token.boxShadow,
            }}
            styles={{ body: { padding: isMobile ? '10px 12px' : '12px 16px' } }}
          >
            <Steps current={currentStep} size={isMobile ? 'small' : 'default'} items={stepItems} />
          </Card>
        </Card>

      {currentStep === 0 && (
      <Card title="上传 TXT 并开始解析" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          <Dragger
            accept=".txt"
            multiple={false}
            beforeUpload={(f) => {
              setFile(f);
              return false;
            }}
            onRemove={() => {
              setFile(null);
            }}
            fileList={
              file
                ? [
                    {
                      uid: 'selected-txt',
                      name: file.name,
                      status: 'done',
                    } as UploadFile,
                  ]
                : []
            }
            style={{ padding: '8px 0' }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽 TXT 文件到此区域</p>
            <p className="ant-upload-hint">首版仅支持 .txt，建议不超过 50MB</p>
          </Dragger>

          <Card size="small" title="解析范围设置">
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              {rangeLocked && (
                <Alert
                  type="warning"
                  showIcon
                  message="当前任务的解析范围已锁定"
                  description="拆书任务会按创建任务时的解析范围执行。若需修改范围，请点击上方“重新开始”后重新上传并解析。"
                />
              )}
              <Select
                value={extractMode}
                onChange={(value) => setExtractMode(value)}
                options={[
                  { label: '截取末 x 章反向生成', value: 'tail' },
                  { label: '整本反向生成', value: 'full' },
                ]}
                style={{ width: '100%' }}
                disabled={rangeLocked}
              />
              <InputNumber
                min={5}
                max={55}
                step={5}
                precision={0}
                value={tailChapterCount}
                disabled={rangeLocked || extractMode !== 'tail'}
                onChange={(value) => setTailChapterCount(typeof value === 'number' ? value : 10)}
                addonBefore="末尾章节数"
                style={{ width: '100%' }}
              />
              <Text type="secondary">
                {effectiveExtractMode === 'tail'
                  ? `当前将截取末 ${normalizedTailChapterCount} 章进行反向生成；章节数必须为 5 的倍数，最多 50 章。`
                  : extractMode === 'tail' && tailChapterCount > 50
                    ? '当前输入已超过 50 章，将自动按整本拆处理。'
                    : '当前将基于整本内容进行反向生成，适合完整拆书但耗时可能更长。'}
              </Text>
            </Space>
          </Card>

          <Card size="small" title="设定填写方式">
            <Radio.Group
              value={setupMode}
              disabled={rangeLocked}
              onChange={(event) => {
                const nextMode = event.target.value as BookImportSetupMode;
                setSetupMode(nextMode);
                setPostImportGeneration(nextMode === 'manual' ? 'manual' : 'auto');
              }}
              style={{ width: '100%' }}
            >
              <Row gutter={[12, 12]}>
                <Col xs={24} md={12}>
                  <Card
                    hoverable={!rangeLocked}
                    size="small"
                    style={{ height: '100%', borderWidth: 2 }}
                    onClick={() => {
                      if (rangeLocked) return;
                      setSetupMode('auto');
                      setPostImportGeneration('auto');
                    }}
                  >
                    <Radio value="auto">
                      <Space direction="vertical" size={4}>
                        <Text strong>AI反向生成预览设定</Text>
                        <Text type="secondary">解析章节后，自动推断项目信息和章节大纲，可在预览页修改。</Text>
                      </Space>
                    </Radio>
                  </Card>
                </Col>
                <Col xs={24} md={12}>
                  <Card
                    hoverable={!rangeLocked}
                    size="small"
                    style={{ height: '100%', borderWidth: 2 }}
                    onClick={() => {
                      if (rangeLocked) return;
                      setSetupMode('manual');
                      setPostImportGeneration('manual');
                    }}
                  >
                    <Radio value="manual">
                      <Space direction="vertical" size={4}>
                        <Text strong>手动填写预览设定</Text>
                        <Text type="secondary">只拆章节并生成可编辑预览，不强制等待AI生成项目信息和后续设定。</Text>
                      </Space>
                    </Radio>
                  </Card>
                </Col>
              </Row>
            </Radio.Group>
          </Card>

          <Alert
            type="info"
            showIcon
            message="支持的拆书 TXT 格式要求"
            description={
              <div style={{ lineHeight: 1.8 }}>
                <div>1. 仅支持 <strong>.txt</strong> 文件，建议每章使用单独的章节标题行。</div>
                <div>2. 推荐格式：<strong>第1章 标题</strong>，下一行开始写正文内容。</div>
                <div>3. 正文建议按自然段换行，首行可缩进两个字符。</div>
                <div>4. 章节之间保留空行即可，不要添加多余的分割线、全文完、导出时间等干扰内容。</div>
                <div style={{ marginTop: 8 }}>
                  示例：
                  <pre style={{ margin: '8px 0 0', padding: 12, borderRadius: 8, background: token.colorFillAlter, whiteSpace: 'pre-wrap' }}>
{`第1章 初入江湖
这里是第1章正文第一段。
这里是第1章正文第二段。

第2章 雨夜追踪
这里是第2章正文内容。`}
                  </pre>
                </div>
              </div>
            }
          />
          
          <Space wrap>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={creatingTask}
              onClick={startTask}
            >
              开始解析
            </Button>
            {taskId && (
              <Tag color="blue">任务ID: {taskId}</Tag>
            )}
          </Space>
        </Space>
      </Card>
      )}

      {currentStep === 1 && (
      <Card title="解析任务状态" style={{ marginBottom: 16 }}>
        {!taskId ? (
          <Empty description="尚未创建任务" />
        ) : (
          <div style={{ textAlign: 'center', padding: '24px 0' }}>
            <Progress
              type="circle"
              percent={taskStatus?.progress || 0}
              status={
                taskStatus?.status === 'failed' ? 'exception' :
                taskStatus?.status === 'completed' ? 'success' :
                'active'
              }
            />
            <div style={{ marginTop: 24 }}>
              <Text strong style={{ fontSize: 16 }}>
                {taskStatus?.status === 'pending' && '等待调度...'}
                {taskStatus?.status === 'running' && '正在解析TXT文件...'}
                {taskStatus?.status === 'completed' && '解析完成！正在生成预览...'}
                {taskStatus?.status === 'failed' && '解析失败'}
                {taskStatus?.status === 'cancelled' && '已取消'}
              </Text>
              {taskStatus?.message && (
                <div style={{ marginTop: 8 }}>
                  <Text type="secondary">{taskStatus.message}</Text>
                </div>
              )}
            </div>

            {taskStatus?.error && (
              <Alert type="error" message={taskStatus.error} showIcon style={{ marginTop: 16, textAlign: 'left' }} />
            )}

            <Space style={{ marginTop: 24 }}>
              <Button icon={<ReloadOutlined />} onClick={refreshStatus}>刷新状态</Button>
              {taskStatus && ['pending', 'running'].includes(taskStatus.status) && (
                <Button danger icon={<StopOutlined />} onClick={cancelTask}>取消任务</Button>
              )}
            </Space>
          </div>
        )}
      </Card>
      )}

      {currentStep === 2 && (
      <>
      <Card
        title="预览修正"
        extra={
          <Button
            type="primary"
            loading={applying}
            disabled={!preview}
            onClick={applyImport}
          >
            确认导入
          </Button>
        }
        style={{ marginBottom: 16 }}
      >
        <Spin spinning={loadingPreview}>
          {!preview ? (
            <Empty description="解析完成后将显示预览数据" />
          ) : (
            <div style={{ maxHeight: '60vh', overflowY: 'auto', paddingRight: 8 }}>
              <Space direction="vertical" style={{ width: '100%' }} size={16}>
              {preview.warnings.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message="检测到告警"
                  description={
                    <ul style={{ margin: 0, paddingLeft: 20 }}>
                      {preview.warnings.map((w, idx) => (
                        <li key={`${w.code}-${idx}`}>[{w.level}] {w.message}</li>
                      ))}
                    </ul>
                  }
                />
              )}

              {preview.split_report && (
                <Card
                  size="small"
                  title="章节切分诊断"
                  extra={
                    <Tag color={preview.split_report.confidence >= 0.75 ? 'green' : preview.split_report.confidence >= 0.55 ? 'orange' : 'red'}>
                      {preview.split_report.mode_label}
                    </Tag>
                  }
                >
                  <Row gutter={[12, 12]} align="middle">
                    <Col xs={24} md={8}>
                      <Text type="secondary">切分置信度</Text>
                      <Progress
                        percent={Math.round((preview.split_report.confidence || 0) * 100)}
                        size="small"
                        status={preview.split_report.confidence >= 0.55 ? 'normal' : 'exception'}
                      />
                    </Col>
                    <Col xs={12} md={4}>
                      <Text type="secondary">问题分类</Text>
                      <div>
                        <Tag color={preview.split_report.problem_category === 'ok' ? 'green' : 'orange'}>
                          {preview.split_report.problem_label || preview.split_report.problem_category}
                        </Tag>
                      </div>
                    </Col>
                    <Col xs={12} md={4}>
                      <Text type="secondary">章节数</Text>
                      <div><Text strong>{preview.split_report.chapter_count}</Text></div>
                    </Col>
                    <Col xs={12} md={4}>
                      <Text type="secondary">平均字数</Text>
                      <div><Text strong>{preview.split_report.average_words}</Text></div>
                    </Col>
                    <Col xs={12} md={4}>
                      <Text type="secondary">最短</Text>
                      <div><Text strong>{preview.split_report.min_words}</Text></div>
                    </Col>
                    <Col xs={12} md={4}>
                      <Text type="secondary">最长</Text>
                      <div><Text strong>{preview.split_report.max_words}</Text></div>
                    </Col>
                    <Col xs={12} md={4}>
                      <Text type="secondary">长度波动</Text>
                      <div><Text strong>{(preview.split_report.size_cv ?? 0).toFixed(2)}</Text></div>
                    </Col>
                    <Col xs={12} md={4}>
                      <Text type="secondary">标题密度</Text>
                      <div><Text strong>{Math.round((preview.split_report.heading_density ?? 0) * 100)}%</Text></div>
                    </Col>
                    {preview.split_report.reasons.length > 0 && (
                      <Col span={24}>
                        <Space size={[6, 6]} wrap>
                          {preview.split_report.reasons.map((reason, idx) => (
                            <Tag key={`${reason}-${idx}`} color={preview.split_report!.confidence >= 0.55 ? 'blue' : 'orange'}>
                              {reason}
                            </Tag>
                          ))}
                        </Space>
                      </Col>
                    )}
                    {preview.split_report.abnormal_chapter_numbers.length > 0 && (
                      <Col span={24}>
                        <Text type="secondary">建议检查章节：</Text>
                        <Text>{preview.split_report.abnormal_chapter_numbers.slice(0, 20).join('、')}</Text>
                      </Col>
                    )}
                  </Row>
                </Card>
              )}

              {preview.token_budget && (
                <Card
                  size="small"
                  title="Token 预算参考"
                  extra={<Text type="secondary">{preview.token_budget.estimated_api_calls} 次 API 调用</Text>}
                >
                  <Row gutter={[12, 12]}>
                    <Col xs={24} md={8}>
                      <Text type="secondary">输入</Text>
                      <div><Text strong>{formatApproxTokens(preview.token_budget.estimated_prompt_tokens)}</Text></div>
                    </Col>
                    <Col xs={24} md={8}>
                      <Text type="secondary">输出</Text>
                      <div><Text strong>{formatApproxTokens(preview.token_budget.estimated_completion_tokens)}</Text></div>
                    </Col>
                    <Col xs={24} md={8}>
                      <Text type="secondary">合计</Text>
                      <div><Text strong>{formatApproxTokens(preview.token_budget.estimated_total_tokens)}</Text></div>
                    </Col>
                    {preview.token_budget.stages.length > 0 && (
                      <Col span={24}>
                        <Space size={[6, 6]} wrap>
                          {preview.token_budget.stages.slice(0, 8).map((stage) => (
                            <Tag key={stage.stage}>
                              {stage.label}：{formatApproxTokens(stage.estimated_total_tokens)}
                            </Tag>
                          ))}
                          {preview.token_budget.stages.length > 8 && (
                            <Tag>另 {preview.token_budget.stages.length - 8} 批</Tag>
                          )}
                        </Space>
                      </Col>
                    )}
                    <Col span={24}>
                      <Text type="secondary">{preview.token_budget.note}</Text>
                    </Col>
                  </Row>
                </Card>
              )}

              {preview.entity_candidates && preview.entity_candidates.length > 0 && (
                <Card
                  size="small"
                  title={`实体预扫描（${preview.entity_candidates.length}）`}
                  extra={<Text type="secondary">已选 {selectedEntityCandidates.length} 个导入为角色/组织</Text>}
                >
                  <List
                    size="small"
                    dataSource={preview.entity_candidates.slice(0, 40)}
                    renderItem={(item) => {
                      const typeLabel = {
                        character: '人物',
                        organization: '组织',
                        location: '地点',
                        item: '物品',
                        unknown: '未知',
                      }[item.entity_type] || '未知';
                      const typeColor = {
                        character: 'cyan',
                        organization: 'purple',
                        location: 'green',
                        item: 'gold',
                        unknown: 'default',
                      }[item.entity_type] || 'default';
                      const candidateKey = bookImportEntityCandidateKey(item);
                      const canImportEntity = item.entity_type === 'character' || item.entity_type === 'organization';
                      const checked = selectedEntityCandidateKeySet.has(candidateKey);
                      const confidence = item.confidence ?? 0.6;
                      const confidenceColor = confidence >= 0.75 ? 'green' : confidence >= 0.5 ? 'orange' : 'default';

                      return (
                        <List.Item>
                          <Space align="start" size={10} style={{ width: '100%' }}>
                            <Checkbox
                              checked={checked}
                              disabled={!canImportEntity}
                              onChange={(event) => {
                                const nextChecked = event.target.checked;
                                setSelectedEntityCandidateKeys((prev) => {
                                  const next = new Set(prev);
                                  if (nextChecked) {
                                    next.add(candidateKey);
                                  } else {
                                    next.delete(candidateKey);
                                  }
                                  return Array.from(next);
                                });
                              }}
                            />
                            <Space direction="vertical" size={4} style={{ width: '100%' }}>
                            <Space size={[8, 4]} wrap>
                              <Text strong>{item.name}</Text>
                              <Tag color={typeColor}>{typeLabel}</Tag>
                              <Tag color={confidenceColor}>置信 {Math.round(confidence * 100)}%</Tag>
                              <Tag>{item.occurrence_count} 次</Tag>
                              {item.first_chapter_number ? (
                                <Text type="secondary">首见第 {item.first_chapter_number} 章</Text>
                              ) : null}
                            </Space>
                            {item.classification_reason && (
                              <Text type="secondary">{item.classification_reason}</Text>
                            )}
                            {item.evidence.length > 0 && (
                              <Text type="secondary">
                                {item.evidence.slice(0, 2).join(' / ')}
                              </Text>
                            )}
                            {!canImportEntity && (
                              <Text type="secondary">地点/物品暂作为证据保留，不写入角色表</Text>
                            )}
                            </Space>
                          </Space>
                        </List.Item>
                      );
                    }}
                  />
                </Card>
              )}

              <Card size="small" title="导入后设定处理">
                <Radio.Group
                  value={postImportGeneration}
                  onChange={(event) => setPostImportGeneration(event.target.value)}
                  style={{ width: '100%' }}
                >
                  <Row gutter={[12, 12]}>
                    <Col xs={24} md={12}>
                      <Card
                        hoverable
                        size="small"
                        style={{ height: '100%', borderWidth: 2 }}
                        onClick={() => setPostImportGeneration('auto')}
                      >
                        <Radio value="auto">
                          <Space direction="vertical" size={4}>
                            <Text strong>AI自动补全设定</Text>
                            <Text type="secondary">导入章节和大纲后，继续生成世界观、职业体系、角色与组织。</Text>
                          </Space>
                        </Radio>
                      </Card>
                    </Col>
                    <Col xs={24} md={12}>
                      <Card
                        hoverable
                        size="small"
                        style={{ height: '100%', borderWidth: 2 }}
                        onClick={() => setPostImportGeneration('manual')}
                      >
                        <Radio value="manual">
                          <Space direction="vertical" size={4}>
                            <Text strong>手动填写设定</Text>
                            <Text type="secondary">只导入项目、大纲和章节，跳过强制AI生成，后续逐项手动或用AI辅助补全。</Text>
                          </Space>
                        </Radio>
                      </Card>
                    </Col>
                  </Row>
                </Radio.Group>
              </Card>

              <Card
                size="small"
                title="项目信息"
              >
                <Row gutter={12}>
                  <Col xs={24} md={12}>
                    {renderSuggestionLabel('title', '标题')}
                    <Input
                      value={preview.project_suggestion.title}
                      onChange={(e) => updateProjectSuggestion({ title: e.target.value })}
                    />
                  </Col>
                  <Col xs={24} md={12}>
                    {renderSuggestionLabel('genre', '类型')}
                    <Input
                      value={preview.project_suggestion.genre}
                      onChange={(e) => updateProjectSuggestion({ genre: e.target.value })}
                    />
                  </Col>
                  <Col xs={24}>
                    {renderSuggestionLabel('theme', '主题')}
                    <TextArea
                      rows={3}
                      value={preview.project_suggestion.theme}
                      onChange={(e) => updateProjectSuggestion({ theme: e.target.value })}
                    />
                  </Col>
                  <Col xs={24}>
                    {renderSuggestionLabel('description', '简介')}
                    <TextArea
                      rows={3}
                      value={preview.project_suggestion.description}
                      onChange={(e) => updateProjectSuggestion({ description: e.target.value })}
                    />
                  </Col>
                  <Col xs={24} md={12}>
                    <Text>叙事角度</Text>
                    <Select
                      style={{ width: '100%' }}
                      value={preview.project_suggestion.narrative_perspective}
                      onChange={(v) => updateProjectSuggestion({ narrative_perspective: v })}
                      options={[
                        { value: '第一人称', label: '第一人称' },
                        { value: '第三人称', label: '第三人称' },
                        { value: '全知视角', label: '全知视角' },
                      ]}
                    />
                  </Col>
                  <Col xs={24} md={12}>
                    <Text>目标字数</Text>
                    <InputNumber
                      style={{ width: '100%' }}
                      min={1000}
                      step={1000}
                      value={preview.project_suggestion.target_words}
                      onChange={(v) => updateProjectSuggestion({ target_words: Number(v || 100000) })}
                    />
                  </Col>
                  {postImportGeneration === 'manual' && (
                    <>
                      <Col xs={24}>
                        {renderSuggestionLabel('world_time_period', '时间背景')}
                        <TextArea
                          rows={2}
                          value={preview.project_suggestion.world_time_period}
                          placeholder="可选：导入时直接写入世界设定"
                          onChange={(e) => updateProjectSuggestion({ world_time_period: e.target.value })}
                        />
                      </Col>
                      <Col xs={24}>
                        {renderSuggestionLabel('world_location', '地理位置')}
                        <TextArea
                          rows={2}
                          value={preview.project_suggestion.world_location}
                          placeholder="可选：故事主要发生地点、势力范围、空间结构..."
                          onChange={(e) => updateProjectSuggestion({ world_location: e.target.value })}
                        />
                      </Col>
                      <Col xs={24}>
                        {renderSuggestionLabel('world_atmosphere', '氛围基调')}
                        <TextArea
                          rows={3}
                          value={preview.project_suggestion.world_atmosphere}
                          placeholder="可选：整体气质、叙事风味、冲突强度..."
                          onChange={(e) => updateProjectSuggestion({ world_atmosphere: e.target.value })}
                        />
                      </Col>
                      <Col xs={24}>
                        {renderSuggestionLabel('world_rules', '世界规则')}
                        <TextArea
                          rows={4}
                          value={preview.project_suggestion.world_rules}
                          placeholder="可选：力量体系、社会规则、禁忌、核心矛盾..."
                          onChange={(e) => updateProjectSuggestion({ world_rules: e.target.value })}
                        />
                      </Col>
                    </>
                  )}
                </Row>
              </Card>

              <Card size="small" title={`章节（${preview.chapters.length}）`}>
                <Collapse
                  items={preview.chapters.map((ch, idx) => ({
                    key: String(idx),
                    label: `第 ${ch.chapter_number} 章 · ${ch.title}`,
                    children: (
                      <Space direction="vertical" style={{ width: '100%' }}>
                        <Space size={8} wrap>
                          <Button size="small" onClick={() => splitPreviewChapter(idx)}>
                            拆分本章
                          </Button>
                          <Button
                            size="small"
                            disabled={idx >= preview.chapters.length - 1}
                            onClick={() => mergeChapterWithNext(idx)}
                          >
                            合并下一章
                          </Button>
                        </Space>
                        <Input
                          value={ch.title}
                          addonBefore="标题"
                          onChange={(e) => updateChapter(idx, { title: e.target.value })}
                        />
                        <TextArea
                          rows={2}
                          value={ch.summary}
                          placeholder="章节摘要"
                          onChange={(e) => updateChapter(idx, { summary: e.target.value })}
                        />
                        <TextArea
                          rows={8}
                          value={ch.content}
                          placeholder="章节正文"
                          onChange={(e) => updateChapter(idx, { content: e.target.value })}
                        />
                      </Space>
                    ),
                  }))}
                />
              </Card>

              </Space>
            </div>
          )}
        </Spin>
      </Card>

      </>
      )}

      {currentStep === 3 && (
      <Card title="生成导入进度" style={{ marginBottom: 16 }}>
        <div style={{ textAlign: 'center', padding: '40px 20px', maxWidth: 600, margin: '0 auto' }}>
          <Typography.Title level={4} style={{ marginBottom: 32 }}>
            {retrying ? '正在重试失败的生成步骤' : (failedSteps.length > 0 && isApplyComplete ? '导入完成，部分步骤需要重试' : '正在为您生成并导入项目内容')}
          </Typography.Title>
          
          <Progress
            percent={retrying ? retryProgress : applyProgress}
            status={
              applyError ? 'exception' :
              (failedSteps.length > 0 && isApplyComplete && !retrying) ? 'exception' :
              (isApplyComplete && failedSteps.length === 0) ? 'success' :
              'active'
            }
            strokeColor={{
              '0%': 'var(--color-primary)',
              '100%': failedSteps.length > 0 ? '#faad14' : 'var(--color-primary-active)',
            }}
            style={{ marginBottom: 24 }}
          />
          
          <Typography.Paragraph
            style={{
              fontSize: 16,
              marginBottom: 32,
              color: applyError ? 'var(--color-error)' :
                (failedSteps.length > 0 && isApplyComplete && !retrying) ? '#faad14' :
                'var(--color-text-secondary)'
            }}
          >
            {retrying ? retryMessage : (applyError || applyMessage)}
          </Typography.Paragraph>
          
          {applyError && (
            <Alert
              type="error"
              message="导入出错"
              description={applyError}
              showIcon
              style={{ textAlign: 'left', marginBottom: 24 }}
            />
          )}

          {/* 步骤失败提示与重试UI */}
          {failedSteps.length > 0 && isApplyComplete && !retrying && (
            <div style={{ textAlign: 'left', marginBottom: 24 }}>
              <Alert
                type="warning"
                icon={<WarningOutlined />}
                showIcon
                message={`${failedSteps.length} 个生成步骤失败`}
                description={
                  <div>
                    <Typography.Paragraph style={{ marginBottom: 12, color: 'rgba(0,0,0,0.65)' }}>
                      以下AI生成步骤未能完成，但基础数据（章节、大纲）已成功导入。您可以选择重试或跳过。
                    </Typography.Paragraph>
                    <List
                      size="small"
                      bordered
                      dataSource={failedSteps}
                      renderItem={(item) => (
                        <List.Item
                          style={{ padding: '8px 12px' }}
                        >
                          <List.Item.Meta
                            title={
                              <Space>
                                <Tag color="error">{item.step_label}</Tag>
                                {(item.retry_count ?? 0) > 0 && (
                                  <Tag color="orange">已重试 {item.retry_count} 次</Tag>
                                )}
                              </Space>
                            }
                            description={
                              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                {item.error.length > 120 ? item.error.slice(0, 120) + '...' : item.error}
                              </Typography.Text>
                            }
                          />
                        </List.Item>
                      )}
                    />
                    <Space style={{ marginTop: 16, display: 'flex', justifyContent: 'center' }}>
                      <Button
                        type="primary"
                        icon={<RedoOutlined />}
                        onClick={retryFailedSteps}
                        loading={retrying}
                      >
                        智能重试全部失败步骤
                      </Button>
                      <Button onClick={skipFailedSteps}>
                        跳过，直接进入项目
                      </Button>
                    </Space>
                  </div>
                }
                style={{ marginBottom: 16 }}
              />
            </div>
          )}

          {/* 重试进行中 */}
          {retrying && (
            <div style={{ marginBottom: 24 }}>
              <Spin spinning={retrying}>
                <Alert
                  type="info"
                  showIcon
                  message="正在重试..."
                  description={retryMessage}
                  style={{ textAlign: 'left' }}
                />
              </Spin>
            </div>
          )}
          
          {!failedSteps.length && !retrying && (
            <div style={{
              background: 'var(--color-bg-layout)',
              padding: 16,
              borderRadius: 8,
              textAlign: 'left',
              marginTop: 32
            }}>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                {postImportGeneration === 'manual' ? (
                  <>
                    当前为手动设定模式：<br />
                    • 仅导入项目基础信息、大纲和章节<br />
                    • 跳过世界观、职业体系、角色与组织的强制AI生成<br />
                    • 进入项目后可在各页面手动填写或使用AI辅助工具补全<br />
                    {isApplyComplete ? '导入已完成，即将自动跳转。' : '请耐心等待，完成后将自动跳转。'}
                  </>
                ) : (
                  <>
                    导入过程中，AI会自动帮您补全：<br />
                    • 世界观设定（时间、地点、氛围、规则）<br />
                    • 职业体系（主职业与副职业）<br />
                    • 核心角色与相关组织<br />
                    {isApplyComplete ? '所有步骤已完成，即将自动跳转。' : '请耐心等待，完成后将自动跳转。'}
                  </>
                )}
              </Typography.Text>
            </div>
          )}
        </div>
      </Card>
      )}

      </div>
    </div>
  );
}
