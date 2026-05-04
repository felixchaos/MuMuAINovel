import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { List, Button, Modal, Form, Input, Select, message, Empty, Space, Badge, Tag, Card, InputNumber, Alert, Radio, Descriptions, Collapse, Popconfirm, Pagination, theme, Upload } from 'antd';
import { EditOutlined, FileTextOutlined, ThunderboltOutlined, LockOutlined, DownloadOutlined, SettingOutlined, FundOutlined, SyncOutlined, CheckCircleOutlined, CloseCircleOutlined, RocketOutlined, StopOutlined, InfoCircleOutlined, CaretRightOutlined, DeleteOutlined, BookOutlined, FormOutlined, PlusOutlined, ReadOutlined, SearchOutlined, FilterOutlined, ClearOutlined, UploadOutlined, HighlightOutlined } from '@ant-design/icons';
import { useStore } from '../store';
import { eventBus } from '../store/eventBus';
import { useChapterSync } from '../store/hooks';
import { generateChapterBackground } from '../services/backgroundTaskService';
import { projectApi, writingStyleApi, chapterApi, polishApi } from '../services/api';
import type { Chapter, ChapterUpdate, ApiError, WritingStyle, AnalysisTask, ExpansionPlanData } from '../types';
import type { TextAreaRef } from 'antd/es/input/TextArea';
import type { UploadFile } from 'antd/es/upload/interface';
import type { FormInstance } from 'antd/es/form';
import ChapterAnalysis from '../components/ChapterAnalysis';
import ExpansionPlanEditor from '../components/ExpansionPlanEditor';
import { SSELoadingOverlay } from '../components/SSELoadingOverlay';
import ChapterReader from '../components/ChapterReader';
import PartialRegenerateToolbar from '../components/PartialRegenerateToolbar';
import PartialRegenerateModal from '../components/PartialRegenerateModal';

const { TextArea } = Input;
const { Dragger } = Upload;

type ChapterAiField = 'title' | 'summary' | 'content';
type ChapterAiMode = 'generate_title' | 'generate_summary' | 'polish' | 'rewrite';
type ChapterFormLike = Pick<FormInstance, 'getFieldValue' | 'setFieldsValue'>;

// localStorage 缓存键名
const WORD_COUNT_CACHE_KEY = 'chapter_default_word_count';
const DEFAULT_WORD_COUNT = 3000;

// 从 localStorage 读取缓存的字数
const getCachedWordCount = (): number => {
  try {
    const cached = localStorage.getItem(WORD_COUNT_CACHE_KEY);
    if (cached) {
      const value = parseInt(cached, 10);
      if (!isNaN(value) && value >= 500 && value <= 10000) {
        return value;
      }
    }
  } catch (error) {
    console.warn('读取字数缓存失败:', error);
  }
  return DEFAULT_WORD_COUNT;
};

// 保存字数到 localStorage
const setCachedWordCount = (value: number): void => {
  try {
    localStorage.setItem(WORD_COUNT_CACHE_KEY, String(value));
  } catch (error) {
    console.warn('保存字数缓存失败:', error);
  }
};

const isAntdValidationError = (error: unknown): boolean => {
  return (
    typeof error === 'object' &&
    error !== null &&
    Array.isArray((error as { errorFields?: unknown }).errorFields)
  );
};

export default function Chapters() {
  const { currentProject, chapters, outlines, setCurrentChapter, setCurrentProject } = useStore();
  const [modal, contextHolder] = Modal.useModal();
  const { token } = theme.useToken();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [isContinuing, setIsContinuing] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form] = Form.useForm();
  const [editorForm] = Form.useForm();
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const contentTextAreaRef = useRef<TextAreaRef>(null);
  const manualContentTextAreaRef = useRef<TextAreaRef>(null);
  const [writingStyles, setWritingStyles] = useState<WritingStyle[]>([]);
  const [selectedStyleId, setSelectedStyleId] = useState<number | undefined>();
  const [targetWordCount, setTargetWordCount] = useState<number>(getCachedWordCount);
  const [availableModels, setAvailableModels] = useState<Array<{ value: string, label: string }>>([]);
  const [selectedModel, setSelectedModel] = useState<string | undefined>();
  const [batchSelectedModel, setBatchSelectedModel] = useState<string | undefined>(); // 批量生成的模型选择
  const [temporaryNarrativePerspective, setTemporaryNarrativePerspective] = useState<string | undefined>(); // 临时人称选择
  const [analysisVisible, setAnalysisVisible] = useState(false);
  const [analysisChapterId, setAnalysisChapterId] = useState<string | null>(null);
  // 分析任务状态管理
  const [analysisTasksMap, setAnalysisTasksMap] = useState<Record<string, AnalysisTask>>({});
  const analysisPollingIntervalRef = useRef<number | null>(null);
  const activeAnalysisPollingIdsRef = useRef<Set<string>>(new Set());

  // 列表查询与分页状态
  const [chapterSearchKeyword, setChapterSearchKeyword] = useState('');
  const [chapterStatusFilter, setChapterStatusFilter] = useState('all');
  const [chapterAnalysisFilter, setChapterAnalysisFilter] = useState('all');
  const [chapterContentFilter, setChapterContentFilter] = useState('all');
  const [chapterOutlineFilter, setChapterOutlineFilter] = useState('all');
  const [chapterPage, setChapterPage] = useState(1);
  const [chapterPageSize, setChapterPageSize] = useState(20);

  // 导出状态
  const [exportModalVisible, setExportModalVisible] = useState(false);
  const [exportRangeType, setExportRangeType] = useState<'all' | 'custom'>('all');
  const [exporting, setExporting] = useState(false);
  const [exportForm] = Form.useForm();

  // 导入状态
  const [importModalVisible, setImportModalVisible] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importMode, setImportMode] = useState<'auto_split' | 'file_as_chapter'>('auto_split');
  const [importPosition, setImportPosition] = useState<'append' | 'custom'>('append');
  const [importFileList, setImportFileList] = useState<UploadFile[]>([]);
  const [importForm] = Form.useForm();

  // 阅读器状态
  const [readerVisible, setReaderVisible] = useState(false);
  const [readingChapter, setReadingChapter] = useState<Chapter | null>(null);

  // 规划编辑状态
  const [planEditorVisible, setPlanEditorVisible] = useState(false);
  const [editingPlanChapter, setEditingPlanChapter] = useState<Chapter | null>(null);

  // 局部重写状态
  const [partialRegenerateToolbarVisible, setPartialRegenerateToolbarVisible] = useState(false);
  const [partialRegenerateToolbarPosition, setPartialRegenerateToolbarPosition] = useState({ top: 0, left: 0 });
  const [selectedTextForRegenerate, setSelectedTextForRegenerate] = useState('');
  const [selectionStartPosition, setSelectionStartPosition] = useState(0);
  const [selectionEndPosition, setSelectionEndPosition] = useState(0);
  const [partialRegenerateModalVisible, setPartialRegenerateModalVisible] = useState(false);
  const [partialRegenerateTitle, setPartialRegenerateTitle] = useState('AI局部重写');

  // 单章节生成进度状态
  const [singleChapterProgress, setSingleChapterProgress] = useState(0);
  const [singleChapterProgressMessage, setSingleChapterProgressMessage] = useState('');


  // 批量生成相关状态
  const [batchGenerateVisible, setBatchGenerateVisible] = useState(false);
  const [batchGenerating, setBatchGenerating] = useState(false);
  const [batchAnalyzingUnanalyzed, setBatchAnalyzingUnanalyzed] = useState(false);
  const [batchTaskId, setBatchTaskId] = useState<string | null>(null);
  const [batchForm] = Form.useForm();
  const [manualCreateForm] = Form.useForm();
  const [batchProgress, setBatchProgress] = useState<{
    status: string;
    total: number;
    completed: number;
    current_chapter_number: number | null;
    estimated_time_minutes?: number;
  } | null>(null);
  const batchPollingIntervalRef = useRef<number | null>(null);

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // 处理文本选中 - 检测选中文本并显示浮动工具栏
  const handleTextSelection = useCallback(() => {
    // 只在编辑器打开时处理选中
    if (!isEditorOpen || isGenerating) {
      setPartialRegenerateToolbarVisible(false);
      return;
    }

    const textArea = contentTextAreaRef.current?.resizableTextArea?.textArea;
    if (!textArea) {
      setPartialRegenerateToolbarVisible(false);
      return;
    }

    if (document.activeElement !== textArea) {
      setPartialRegenerateToolbarVisible(false);
      return;
    }

    // 获取 textarea 中的选中位置
    const start = textArea.selectionStart;
    const end = textArea.selectionEnd;
    const textContent = textArea.value;
    const selectedInTextArea = textContent.substring(start, end);

    if (selectedInTextArea.trim().length < 10) {
      setPartialRegenerateToolbarVisible(false);
      return;
    }

    // 计算浮动工具栏位置
    const rect = textArea.getBoundingClientRect();
    const computedStyle = window.getComputedStyle(textArea);
    const lineHeight = parseFloat(computedStyle.lineHeight) || 24;
    const paddingTop = parseFloat(computedStyle.paddingTop) || 0;
    
    // 计算选中文本起始位置所在的行号
    const textBeforeSelection = textContent.substring(0, start);
    const startLine = textBeforeSelection.split('\n').length - 1;
    
    // 计算选中文本在 textarea 中的视觉位置
    // 需要考虑 scrollTop（textarea 内部滚动偏移）
    const scrollTop = textArea.scrollTop;
    const visualTop = (startLine * lineHeight) + paddingTop - scrollTop;
    
    // 工具栏位置：textarea 顶部 + 选中文本的视觉位置 - 工具栏高度偏移
    const toolbarTop = rect.top + visualTop - 45;
    
    // 水平位置：放在 textarea 的右侧区域，避免遮挡文本
    const toolbarLeft = rect.right - 180;

    setSelectedTextForRegenerate(selectedInTextArea);
    setSelectionStartPosition(start);
    setSelectionEndPosition(end);
    
    // 计算工具栏位置，如果选中位置不在可视区域内，固定在边缘
    let finalTop = toolbarTop;
    if (visualTop < 0) {
      finalTop = rect.top + 10;
    } else if (visualTop > textArea.clientHeight) {
      finalTop = rect.bottom - 50;
    }
    
    setPartialRegenerateToolbarPosition({
      top: Math.max(rect.top + 10, Math.min(finalTop, rect.bottom - 50)),
      left: Math.min(Math.max(rect.left + 20, toolbarLeft), window.innerWidth - 200),
    });
    setPartialRegenerateToolbarVisible(true);
  }, [isEditorOpen, isGenerating]);

  // 更新工具栏位置的函数（不检测选中，只更新位置）
  const updateToolbarPosition = useCallback(() => {
    if (!partialRegenerateToolbarVisible || !selectedTextForRegenerate) return;
    
    const textArea = contentTextAreaRef.current?.resizableTextArea?.textArea;
    if (!textArea) return;
    
    const rect = textArea.getBoundingClientRect();
    const computedStyle = window.getComputedStyle(textArea);
    const lineHeight = parseFloat(computedStyle.lineHeight) || 24;
    const paddingTop = parseFloat(computedStyle.paddingTop) || 0;
    
    const textContent = textArea.value;
    const textBeforeSelection = textContent.substring(0, selectionStartPosition);
    const startLine = textBeforeSelection.split('\n').length - 1;
    
    const scrollTop = textArea.scrollTop;
    const visualTop = (startLine * lineHeight) + paddingTop - scrollTop;
    
    const toolbarTop = rect.top + visualTop - 45;
    // 固定在 textarea 右上角，不随选中位置变化
    const toolbarLeft = rect.right - 180;
    
    // 工具栏固定在 textarea 可视区域内，即使选中文本滚出视野也保持显示
    // 如果选中位置在可视区域内，跟随选中位置
    // 如果滚出视野，固定在顶部或底部边缘
    let finalTop = toolbarTop;
    if (visualTop < 0) {
      // 选中位置在上方视野外，工具栏固定在顶部
      finalTop = rect.top + 10;
    } else if (visualTop > textArea.clientHeight) {
      // 选中位置在下方视野外，工具栏固定在底部
      finalTop = rect.bottom - 50;
    }
    
    setPartialRegenerateToolbarPosition({
      top: Math.max(rect.top + 10, Math.min(finalTop, rect.bottom - 50)),
      left: Math.min(Math.max(rect.left + 20, toolbarLeft), window.innerWidth - 200),
    });
  }, [partialRegenerateToolbarVisible, selectedTextForRegenerate, selectionStartPosition]);

  // 监听选中事件
  useEffect(() => {
    if (!isEditorOpen) return;

    const textArea = contentTextAreaRef.current?.resizableTextArea?.textArea;
    if (!textArea) return;

    const handleMouseUp = () => {
      // 鼠标释放时检查选中
      setTimeout(handleTextSelection, 50);
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      // Shift + 方向键选中时检查
      if (e.shiftKey && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) {
        setTimeout(handleTextSelection, 50);
      }
    };

    const handleScroll = () => {
      // 滚动时更新位置（使用 requestAnimationFrame 优化性能）
      requestAnimationFrame(updateToolbarPosition);
    };

    // 监听 textarea 滚动
    textArea.addEventListener('mouseup', handleMouseUp);
    textArea.addEventListener('keyup', handleKeyUp);
    textArea.addEventListener('scroll', handleScroll);

    // 同时监听 Modal body 滚动（Modal 内容可能在外层容器滚动）
    const modalBody = textArea.closest('.ant-modal-body');
    if (modalBody) {
      modalBody.addEventListener('scroll', handleScroll);
    }

    // 监听窗口大小变化
    window.addEventListener('resize', handleScroll);

    return () => {
      textArea.removeEventListener('mouseup', handleMouseUp);
      textArea.removeEventListener('keyup', handleKeyUp);
      textArea.removeEventListener('scroll', handleScroll);
      if (modalBody) {
        modalBody.removeEventListener('scroll', handleScroll);
      }
      window.removeEventListener('resize', handleScroll);
    };
  }, [isEditorOpen, handleTextSelection, updateToolbarPosition]);

  // 点击其他区域时隐藏工具栏
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      
      // 如果点击的是工具栏，不隐藏
      if (target.closest('[data-partial-regenerate-toolbar]')) {
        return;
      }
      
      // 如果点击的是 textarea，不隐藏
      if (target.tagName === 'TEXTAREA') {
        return;
      }
      
      // 如果点击的是 Modal 内部（包括滚动条），不隐藏
      if (target.closest('.ant-modal-content')) {
        return;
      }
      
      // 点击 Modal 外部才隐藏工具栏
      setPartialRegenerateToolbarVisible(false);
    };

    if (partialRegenerateToolbarVisible) {
      document.addEventListener('click', handleClickOutside);
      return () => document.removeEventListener('click', handleClickOutside);
    }
  }, [partialRegenerateToolbarVisible]);

  const {
    refreshChapters,
    updateChapter,
    deleteChapter,
    generateChapterContentStream
  } = useChapterSync();

  useEffect(() => {
    if (currentProject?.id) {
      refreshChapters();
      loadWritingStyles();
      loadAnalysisTasks();
      checkAndRestoreBatchTask();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProject?.id]);

  // 清理轮询定时器
  useEffect(() => {
    const batchPollingInterval = batchPollingIntervalRef.current;
    return () => {
      if (analysisPollingIntervalRef.current) {
        clearInterval(analysisPollingIntervalRef.current);
        analysisPollingIntervalRef.current = null;
      }
      if (batchPollingInterval) {
        clearInterval(batchPollingInterval);
      }
    };
  }, []);

  const clearAnalysisPollingIfIdle = useCallback(() => {
    if (activeAnalysisPollingIdsRef.current.size === 0 && analysisPollingIntervalRef.current) {
      clearInterval(analysisPollingIntervalRef.current);
      analysisPollingIntervalRef.current = null;
    }
  }, []);

  const pollActiveAnalysisTasks = useCallback(async () => {
    if (!currentProject?.id) return;

    const activeIds = Array.from(activeAnalysisPollingIdsRef.current);
    if (activeIds.length === 0) {
      clearAnalysisPollingIfIdle();
      return;
    }

    try {
      const response = await chapterApi.getBatchAnalysisStatuses(currentProject.id, activeIds);
      const tasksMap = response.items || {};

      setAnalysisTasksMap(prev => ({
        ...prev,
        ...tasksMap,
      }));

      activeIds.forEach((chapterId) => {
        const task = tasksMap[chapterId];
        if (!task || task.status === 'completed' || task.status === 'failed' || task.status === 'none') {
          activeAnalysisPollingIdsRef.current.delete(chapterId);

          if (task?.status === 'completed') {
            message.success('章节分析完成');
          } else if (task?.status === 'failed') {
            message.error(`章节分析失败: ${task.error_message || '未知错误'}`);
          }
        }
      });

      clearAnalysisPollingIfIdle();
    } catch (error) {
      console.error('批量轮询分析任务失败:', error);
    }
  }, [clearAnalysisPollingIfIdle, currentProject?.id]);

  const ensureAnalysisPolling = useCallback(() => {
    if (analysisPollingIntervalRef.current) return;

    analysisPollingIntervalRef.current = window.setInterval(() => {
      void pollActiveAnalysisTasks();
    }, 2000);

    // 立即执行一次
    void pollActiveAnalysisTasks();
  }, [pollActiveAnalysisTasks]);

  // 加载所有章节的分析任务状态（批量接口，避免逐章请求风暴）
  // 接受可选的 chaptersToLoad 参数，解决 React 状态更新延迟导致的问题
  const loadAnalysisTasks = async (chaptersToLoad?: typeof chapters) => {
    const targetChapters = chaptersToLoad || chapters;
    if (!targetChapters || targetChapters.length === 0 || !currentProject?.id) return;

    const chapterIds = targetChapters
      .filter(chapter => chapter.content && chapter.content.trim() !== '')
      .map(chapter => chapter.id);

    if (chapterIds.length === 0) {
      setAnalysisTasksMap({});
      activeAnalysisPollingIdsRef.current.clear();
      clearAnalysisPollingIfIdle();
      return;
    }

    try {
      const response = await chapterApi.getBatchAnalysisStatuses(currentProject.id, chapterIds);
      const tasksMap = response.items || {};
      setAnalysisTasksMap(tasksMap);

      activeAnalysisPollingIdsRef.current.clear();
      Object.entries(tasksMap).forEach(([chapterId, task]) => {
        if (task?.status === 'pending' || task?.status === 'running') {
          activeAnalysisPollingIdsRef.current.add(chapterId);
        }
      });

      if (activeAnalysisPollingIdsRef.current.size > 0) {
        ensureAnalysisPolling();
      } else {
        clearAnalysisPollingIfIdle();
      }
    } catch (error) {
      console.error('批量加载分析任务状态失败:', error);
    }
  };

  // 启动单个章节的任务轮询（内部合并到批量轮询）
  const startPollingTask = (chapterId: string) => {
    activeAnalysisPollingIdsRef.current.add(chapterId);
    ensureAnalysisPolling();
  };

  const loadWritingStyles = async () => {
    if (!currentProject?.id) return;

    try {
      const response = await writingStyleApi.getProjectStyles(currentProject.id);
      setWritingStyles(response.styles);

      // 设置默认风格为初始选中
      const defaultStyle = response.styles.find(s => s.is_default);
      if (defaultStyle) {
        setSelectedStyleId(defaultStyle.id);
      }
    } catch (error) {
      console.error('加载写作风格失败:', error);
      message.error('加载写作风格失败');
    }
  };

  const loadAvailableModels = async () => {
    try {
      // 从设置API获取用户配置的模型列表
      const settingsResponse = await fetch('/api/settings');
      if (settingsResponse.ok) {
        const settings = await settingsResponse.json();
        const { api_key, api_base_url, api_provider } = settings;

        if (api_key && api_base_url) {
          try {
            const modelsResponse = await fetch(
              `/api/settings/models?api_key=${encodeURIComponent(api_key)}&api_base_url=${encodeURIComponent(api_base_url)}&provider=${api_provider}`
            );
            if (modelsResponse.ok) {
              const data = await modelsResponse.json();
              if (data.models && data.models.length > 0) {
                setAvailableModels(data.models);
                // 设置默认模型为当前配置的模型
                setSelectedModel(settings.llm_model);
                return settings.llm_model; // 返回模型名称
              }
            }
          } catch {
            console.log('获取模型列表失败，将使用默认模型');
          }
        }
      }
    } catch (error) {
      console.error('加载可用模型失败:', error);
    }
    return null;
  };

  // 检查并恢复批量生成任务
  const checkAndRestoreBatchTask = async () => {
    if (!currentProject?.id) return;

    try {
      const response = await fetch(`/api/chapters/project/${currentProject.id}/batch-generate/active`);
      if (!response.ok) return;

      const data = await response.json();

      if (data.has_active_task && data.task) {
        const task = data.task;

        // 恢复任务状态（只在顶部进度条显示，不弹出Modal）
        setBatchTaskId(task.batch_id);
        setBatchProgress({
          status: task.status,
          total: task.total,
          completed: task.completed,
          current_chapter_number: task.current_chapter_number,
        });
        setBatchGenerating(true);
        // 不设置 setBatchGenerateVisible(true)，避免弹出Modal遮挡页面

        // 启动轮询
        startBatchPolling(task.batch_id);

        message.info('检测到未完成的批量生成任务，请查看任务列表');
      }
    } catch (error) {
      console.error('检查批量生成任务失败:', error);
    }
  };

  // 🔔 显示浏览器通知
  const showBrowserNotification = (title: string, body: string, type: 'success' | 'error' | 'info' = 'info') => {
    // 检查浏览器是否支持通知
    if (!('Notification' in window)) {
      console.log('浏览器不支持通知功能');
      return;
    }

    // 检查通知权限
    if (Notification.permission === 'granted') {
      // 选择图标
      const icon = type === 'success' ? '/logo.svg' : type === 'error' ? '/favicon.ico' : '/logo.svg';
      
      const notification = new Notification(title, {
        body,
        icon,
        badge: '/favicon.ico',
        tag: 'batch-generation', // 相同tag会替换旧通知
        requireInteraction: false, // 自动关闭
        silent: false, // 播放提示音
      });

      // 点击通知时聚焦到窗口
      notification.onclick = () => {
        window.focus();
        notification.close();
      };

      // 5秒后自动关闭
      setTimeout(() => {
        notification.close();
      }, 5000);
    } else if (Notification.permission !== 'denied') {
      // 如果权限未被明确拒绝，尝试请求权限
      Notification.requestPermission().then(permission => {
        if (permission === 'granted') {
          showBrowserNotification(title, body, type);
        }
      });
    }
  };

  // 按章节号排序并按大纲分组章节 (必须在早返回之前调用，避免违反 Hooks 规则)
  const { sortedChapters } = useMemo(() => {
    const sorted = [...chapters].sort((a, b) => a.chapter_number - b.chapter_number);

    const groups: Record<string, {
      outlineId: string | null;
      outlineTitle: string;
      outlineOrder: number;
      chapters: Chapter[];
    }> = {};

    sorted.forEach(chapter => {
      const key = chapter.outline_id || 'uncategorized';

      if (!groups[key]) {
        groups[key] = {
          outlineId: chapter.outline_id || null,
          outlineTitle: chapter.outline_title || '未分类章节',
          outlineOrder: chapter.outline_order ?? 999,
          chapters: []
        };
      }

      groups[key].chapters.push(chapter);
    });

    return { sortedChapters: sorted };
  }, [chapters]);

  const chapterOutlineOptions = useMemo(() => {
    const optionMap = new Map<string, string>();
    sortedChapters.forEach((chapter) => {
      const key = chapter.outline_id || 'no_outline';
      const label = chapter.outline_title || '未关联大纲';
      if (!optionMap.has(key)) {
        optionMap.set(key, label);
      }
    });

    return Array.from(optionMap.entries()).map(([value, label]) => ({ value, label }));
  }, [sortedChapters]);

  // 章节查询过滤（前端过滤，减少渲染压力）
  const filteredSortedChapters = useMemo(() => {
    const keyword = chapterSearchKeyword.trim().toLowerCase();

    return sortedChapters.filter((chapter) => {
      const matchesKeyword = !keyword || (
        String(chapter.chapter_number).includes(keyword) ||
        chapter.title.toLowerCase().includes(keyword) ||
        (chapter.outline_title || '').toLowerCase().includes(keyword)
      );

      const matchesStatus = chapterStatusFilter === 'all' || chapter.status === chapterStatusFilter;

      const task = analysisTasksMap[chapter.id];
      const isAnalyzing = task?.status === 'pending' || task?.status === 'running';
      const isAnalyzed = task?.status === 'completed';
      const isAnalysisFailed = task?.status === 'failed';
      const isUnanalyzed = !task || !task.has_task || task.status === 'none';
      const matchesAnalysis =
        chapterAnalysisFilter === 'all' ||
        (chapterAnalysisFilter === 'completed' && isAnalyzed) ||
        (chapterAnalysisFilter === 'unanalyzed' && isUnanalyzed) ||
        (chapterAnalysisFilter === 'running' && isAnalyzing) ||
        (chapterAnalysisFilter === 'failed' && isAnalysisFailed);

      const hasContent = Boolean(chapter.content && chapter.content.trim() !== '');
      const matchesContent =
        chapterContentFilter === 'all' ||
        (chapterContentFilter === 'has_content' && hasContent) ||
        (chapterContentFilter === 'empty' && !hasContent);

      const outlineKey = chapter.outline_id || 'no_outline';
      const matchesOutline = chapterOutlineFilter === 'all' || outlineKey === chapterOutlineFilter;

      return matchesKeyword && matchesStatus && matchesAnalysis && matchesContent && matchesOutline;
    });
  }, [
    sortedChapters,
    chapterSearchKeyword,
    chapterStatusFilter,
    chapterAnalysisFilter,
    chapterContentFilter,
    chapterOutlineFilter,
    analysisTasksMap,
  ]);

  // 分页后的扁平章节
  const pagedSortedChapters = useMemo(() => {
    const start = (chapterPage - 1) * chapterPageSize;
    return filteredSortedChapters.slice(start, start + chapterPageSize);
  }, [filteredSortedChapters, chapterPage, chapterPageSize]);

  // one-to-many 模式分页后再按大纲分组
  const pagedGroupedChapters = useMemo(() => {
    const groups: Record<string, {
      outlineId: string | null;
      outlineTitle: string;
      outlineOrder: number;
      chapters: Chapter[];
    }> = {};

    pagedSortedChapters.forEach(chapter => {
      const key = chapter.outline_id || 'uncategorized';
      if (!groups[key]) {
        groups[key] = {
          outlineId: chapter.outline_id || null,
          outlineTitle: chapter.outline_title || '未分类章节',
          outlineOrder: chapter.outline_order ?? 999,
          chapters: []
        };
      }
      groups[key].chapters.push(chapter);
    });

    return Object.values(groups).sort((a, b) => a.outlineOrder - b.outlineOrder);
  }, [pagedSortedChapters]);

  // 搜索词或分页大小变化时重置到第一页
  useEffect(() => {
    setChapterPage(1);
  }, [
    chapterSearchKeyword,
    chapterStatusFilter,
    chapterAnalysisFilter,
    chapterContentFilter,
    chapterOutlineFilter,
    chapterPageSize,
    currentProject?.outline_mode,
  ]);

  // 数据变化导致页码越界时自动纠正
  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(filteredSortedChapters.length / chapterPageSize));
    if (chapterPage > maxPage) {
      setChapterPage(maxPage);
    }
  }, [filteredSortedChapters.length, chapterPage, chapterPageSize]);

  // 预计算每章可生成状态，避免在渲染阶段重复 O(n²) 扫描
  const chapterGenerateGateMap = useMemo(() => {
    const gateMap: Record<string, { canGenerate: boolean; reason: string }> = {};
    const incompleteChapterNumbers: number[] = [];
    const unanalyzedChapters: Array<{ chapterNumber: number; reason: string }> = [];

    sortedChapters.forEach((chapter) => {
      if (incompleteChapterNumbers.length > 0) {
        gateMap[chapter.id] = {
          canGenerate: false,
          reason: `需要先完成前置章节：第 ${incompleteChapterNumbers.join('、')} 章`
        };
      } else if (unanalyzedChapters.length > 0) {
        gateMap[chapter.id] = {
          canGenerate: false,
          reason: `需要先分析前置章节：第 ${unanalyzedChapters.map(c => c.chapterNumber).join('、')} 章 (${unanalyzedChapters.map(c => c.reason).join('、')})`
        };
      } else {
        gateMap[chapter.id] = { canGenerate: true, reason: '' };
      }

      // 将当前章纳入“后续章节”的前置条件
      if (!chapter.content || chapter.content.trim() === '') {
        incompleteChapterNumbers.push(chapter.chapter_number);
      }

      const task = analysisTasksMap[chapter.id];
      if (!task || !task.has_task) {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: '未分析' });
      } else if (task.status === 'pending') {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: '等待分析' });
      } else if (task.status === 'running') {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: '分析中' });
      } else if (task.status === 'failed') {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: '分析失败' });
      } else if (task.status !== 'completed') {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: '状态未知' });
      }
    });

    return gateMap;
  }, [sortedChapters, analysisTasksMap]);

  // 当前可被“一键分析”的章节（有内容且未处于完成/进行中）
  const batchAnalyzableChapterCount = useMemo(() => {
    return sortedChapters.filter((chapter) => {
      if (!chapter.content || chapter.content.trim() === '') return false;
      const task = analysisTasksMap[chapter.id];
      if (!task || !task.has_task) return true;
      return task.status !== 'completed' && task.status !== 'pending' && task.status !== 'running';
    }).length;
  }, [sortedChapters, analysisTasksMap]);

  const hasActiveChapterFilters =
    chapterSearchKeyword.trim() !== '' ||
    chapterStatusFilter !== 'all' ||
    chapterAnalysisFilter !== 'all' ||
    chapterContentFilter !== 'all' ||
    chapterOutlineFilter !== 'all';

  if (!currentProject) return null;

  // 获取人称的中文显示文本（同时支持中英文值）
  const getNarrativePerspectiveText = (perspective?: string): string => {
    const texts: Record<string, string> = {
      // 英文值映射（向后兼容）
      'first_person': '第一人称（我）',
      'third_person': '第三人称（他/她）',
      'omniscient': '全知视角',
      // 中文值映射（项目设置使用）
      '第一人称': '第一人称（我）',
      '第三人称': '第三人称（他/她）',
      '全知视角': '全知视角',
    };
    return texts[perspective || ''] || '第三人称（默认）';
  };

  const canGenerateChapter = (chapter: Chapter): boolean => {
    return chapterGenerateGateMap[chapter.id]?.canGenerate ?? true;
  };

  const getGenerateDisabledReason = (chapter: Chapter): string => {
    return chapterGenerateGateMap[chapter.id]?.reason || '';
  };

  const getChapterFormText = (targetForm: ChapterFormLike, field: ChapterAiField) => {
    return String(targetForm.getFieldValue(field) || '');
  };

  const buildChapterFormContext = (targetForm: ChapterFormLike) => {
    const chapterNumber = targetForm.getFieldValue('chapter_number');
    const outlineId = String(targetForm.getFieldValue('outline_id') || '');
    const outline = outlineId ? outlines.find(item => item.id === outlineId) : undefined;
    const title = getChapterFormText(targetForm, 'title').trim();
    const summary = getChapterFormText(targetForm, 'summary').trim();
    const content = getChapterFormText(targetForm, 'content').trim();
    const clippedContent = content.length > 12000
      ? `${content.slice(0, 7000)}\n\n……（中间内容已压缩）……\n\n${content.slice(-4000)}`
      : content;

    return [
      `项目：${currentProject.title}`,
      chapterNumber ? `章节序号：第${chapterNumber}章` : '',
      outline ? `关联大纲：${outline.title}\n${outline.content || ''}` : '',
      title ? `当前标题：${title}` : '',
      summary ? `当前摘要：${summary}` : '',
      clippedContent ? `章节正文：\n${clippedContent}` : '',
    ].filter(Boolean).join('\n\n');
  };

  const buildChapterAiInstruction = (
    mode: ChapterAiMode,
    label: string,
    extraInstruction: string
  ) => {
    const extra = extraInstruction.trim();
    const baseInstructions: Record<ChapterAiMode, string> = {
      generate_title:
        '请根据给定章节上下文生成一个中文网文章节标题。要求：只输出标题本身；不要输出解释、引号、书名号或前后缀；标题要贴合本章核心事件，简洁有辨识度，尽量控制在2到12个汉字。',
      generate_summary:
        '请根据给定章节上下文生成章节摘要。要求：保留真实剧情事实、人设状态、关键冲突和结尾落点；不要新增设定；不要写成宣传语；控制在100到220字；只输出摘要正文。',
      polish:
        `请润色${label}。要求：保留原意、事实、人设、叙事视角和关键信息；表达更自然、更像人写；不要新增设定；不要输出解释或前后缀，只输出处理后的文本。`,
      rewrite:
        `请根据用户要求重写${label}。要求：保留必要事实、人设和前后文逻辑；允许重组表达和段落节奏；不要输出解释或前后缀，只输出重写后的文本。`,
    };

    return extra
      ? `${baseInstructions[mode]}\n\n用户额外要求：${extra}`
      : baseInstructions[mode];
  };

  const renderChapterAiStreamContent = (
    originalText: string,
    resultText: string,
    progress: number,
    progressMessage: string,
    status: 'processing' | 'success' | 'error'
  ) => {
    const isDone = status === 'success';
    const isError = status === 'error';

    return (
      <div style={{ marginTop: 12 }}>
        <Alert
          type={isError ? 'error' : isDone ? 'success' : 'info'}
          showIcon
          message={progressMessage || (isDone ? 'AI 已生成完成，确认后才会替换当前内容。' : 'AI 正在生成，结果会实时显示。')}
          description={isError ? undefined : `进度 ${progress}% · 已生成 ${resultText.length} 字`}
          style={{ marginBottom: 12 }}
        />
        <div style={{ display: 'grid', gap: 12 }}>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>原文/上下文</div>
            <div style={{
              maxHeight: 150,
              overflowY: 'auto',
              whiteSpace: 'pre-wrap',
              lineHeight: 1.6,
              padding: '8px 10px',
              border: `1px solid ${token.colorBorderSecondary}`,
              borderRadius: token.borderRadius,
              background: token.colorFillQuaternary,
              color: token.colorTextSecondary,
            }}>
              {originalText || '（空）'}
            </div>
          </div>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>AI结果（流式）</div>
            <div style={{
              minHeight: 120,
              maxHeight: 260,
              overflowY: 'auto',
              whiteSpace: 'pre-wrap',
              lineHeight: 1.7,
              padding: '8px 10px',
              border: `1px solid ${isError ? token.colorErrorBorder : token.colorPrimaryBorder}`,
              borderRadius: token.borderRadius,
              background: token.colorBgContainer,
            }}>
              {resultText || '等待生成...'}
            </div>
          </div>
        </div>
      </div>
    );
  };

  const runChapterAiStream = async (
    label: string,
    sourceText: string,
    instruction: string,
    temperature: number,
    onApply: (resultText: string) => void
  ) => {
    let resultText = '';
    let progress = 0;
    let progressMessage = '准备连接AI...';
    let status: 'processing' | 'success' | 'error' = 'processing';
    let completed = false;
    let lastRenderAt = 0;
    const abortController = new AbortController();

    const resultModal = modal.confirm({
      title: `${label} AI结果`,
      icon: <HighlightOutlined />,
      width: isMobile ? 'calc(100vw - 32px)' : 760,
      centered: true,
      okText: '应用结果',
      cancelText: '取消生成',
      okButtonProps: { disabled: true, loading: true },
      content: renderChapterAiStreamContent(sourceText, resultText, progress, progressMessage, status),
      onOk: () => {
        if (!completed || !resultText.trim()) {
          return Promise.reject();
        }
        onApply(resultText.trim());
        message.success(`${label}已应用AI结果`);
      },
      onCancel: () => {
        if (!completed) {
          abortController.abort();
        }
      },
    });

    const updateResultModal = (force = false) => {
      const now = Date.now();
      if (!force && now - lastRenderAt < 120) return;
      lastRenderAt = now;

      resultModal.update({
        content: renderChapterAiStreamContent(sourceText, resultText, progress, progressMessage, status),
        okButtonProps: {
          disabled: !completed || !resultText.trim() || status === 'error',
          loading: !completed && status !== 'error',
        },
        cancelText: completed ? '保留原文' : '取消生成',
      });
    };

    try {
      const result = await polishApi.polishTextStream({
        original_text: sourceText,
        project_id: currentProject.id,
        model: selectedModel || undefined,
        temperature,
        instruction,
      }, {
        signal: abortController.signal,
        onProgress: (messageText, progressValue, streamStatus) => {
          progress = progressValue;
          progressMessage = messageText || progressMessage;
          if (streamStatus === 'error') {
            status = 'error';
          }
          updateResultModal();
        },
        onChunk: (content) => {
          resultText += content;
          updateResultModal();
        },
        onError: (error) => {
          status = 'error';
          progressMessage = error || 'AI处理失败';
          completed = true;
          updateResultModal(true);
        },
      });

      resultText = (result.polished_text || resultText).trim();
      progress = 100;
      progressMessage = 'AI处理完成，确认后才会替换当前内容。';
      status = 'success';
      completed = true;
      updateResultModal(true);
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        message.info(`${label}生成已取消`);
        return;
      }

      console.error(`${label} AI流式处理失败:`, error);
      status = 'error';
      progressMessage = (error as Error).message || 'AI处理失败';
      completed = true;
      updateResultModal(true);
    }
  };

  const runChapterAiTool = async (
    targetForm: ChapterFormLike,
    field: ChapterAiField,
    label: string,
    mode: ChapterAiMode,
    extraInstruction: string
  ) => {
    const currentValue = getChapterFormText(targetForm, field).trim();
    const contextText = buildChapterFormContext(targetForm);
    const sourceText = mode === 'generate_title' || mode === 'generate_summary'
      ? contextText
      : currentValue;

    if ((mode === 'polish' || mode === 'rewrite') && !currentValue) {
      message.warning(`请先填写${label}`);
      return;
    }

    const hasUsefulContext = Boolean(
      getChapterFormText(targetForm, 'title').trim() ||
      getChapterFormText(targetForm, 'summary').trim() ||
      getChapterFormText(targetForm, 'content').trim() ||
      targetForm.getFieldValue('outline_id')
    );

    if ((mode === 'generate_title' || mode === 'generate_summary') && !hasUsefulContext) {
      message.warning('请先填写正文、摘要或选择关联大纲，再让AI生成');
      return;
    }

    await runChapterAiStream(
      label,
      sourceText,
      buildChapterAiInstruction(mode, label, extraInstruction),
      mode === 'polish' ? 0.7 : 0.55,
      (aiText) => {
        targetForm.setFieldsValue({ [field]: aiText });
      }
    );
  };

  const openChapterAiTool = (
    targetForm: ChapterFormLike,
    field: ChapterAiField,
    label: string,
    mode: ChapterAiMode
  ) => {
    let extraInstruction = '';
    const actionText = mode === 'generate_title' || mode === 'generate_summary'
      ? '生成'
      : mode === 'rewrite'
        ? '重写'
        : '润色';

    modal.confirm({
      title: `${label}${actionText}要求`,
      icon: <HighlightOutlined />,
      width: isMobile ? 'calc(100vw - 32px)' : 640,
      centered: true,
      okText: `开始${actionText}`,
      cancelText: '取消',
      content: (
        <div style={{ marginTop: 12 }}>
          <div style={{ marginBottom: 12, color: token.colorTextSecondary }}>
            输入本次希望 AI 如何处理；留空则使用默认规则。
          </div>
          <TextArea
            rows={4}
            placeholder="例如：更凝练；强化悬疑感；保留所有事实；不要新增设定；标题更有番茄风格..."
            autoFocus
            onChange={(event) => {
              extraInstruction = event.target.value;
            }}
          />
        </div>
      ),
      onOk: () => {
        void runChapterAiTool(targetForm, field, label, mode, extraInstruction);
      },
    });
  };

  const openSelectedContentAiTool = (
    targetForm: ChapterFormLike,
    textAreaRef: { current: TextAreaRef | null }
  ) => {
    const textArea = textAreaRef.current?.resizableTextArea?.textArea;
    if (!textArea) {
      message.warning('请先聚焦章节正文输入框');
      return;
    }

    const start = textArea.selectionStart;
    const end = textArea.selectionEnd;
    const selectedText = textArea.value.substring(start, end);

    if (start === end || selectedText.trim().length < 10) {
      message.warning('请先在章节正文中选中至少10个字');
      return;
    }

    let extraInstruction = '';
    modal.confirm({
      title: '选中内容编辑要求',
      icon: <HighlightOutlined />,
      width: isMobile ? 'calc(100vw - 32px)' : 640,
      centered: true,
      okText: '开始编辑',
      cancelText: '取消',
      content: (
        <div style={{ marginTop: 12 }}>
          <div style={{ marginBottom: 12, color: token.colorTextSecondary }}>
            AI 只会处理选中的这段文字，确认后才会替换选区。
          </div>
          <TextArea
            rows={4}
            placeholder="例如：改成更自然的对白；补足动作细节；压缩这段；保持设定不变..."
            autoFocus
            onChange={(event) => {
              extraInstruction = event.target.value;
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
            {selectedText}
          </div>
        </div>
      ),
      onOk: () => {
        const contextText = buildChapterFormContext(targetForm);
        void runChapterAiStream(
          '选中内容',
          selectedText,
          [
            '你是中文小说编辑。请只处理用户选中的片段，保持章节上下文、人设、事实和叙事视角一致。只输出处理后的选中片段，不要解释，不要补前后缀。',
            extraInstruction.trim() ? `用户要求：${extraInstruction.trim()}` : '用户要求：自然润色并改善表达。',
            `章节上下文：\n${contextText}`,
          ].join('\n\n'),
          0.65,
          (aiText) => {
            const currentContent = getChapterFormText(targetForm, 'content');
            let replaceStart = start;
            let replaceEnd = end;

            if (currentContent.substring(start, end) !== selectedText) {
              const fallbackStart = currentContent.indexOf(selectedText);
              if (fallbackStart < 0) {
                message.error('正文已变化，无法定位选中内容，请重新选择');
                return;
              }
              replaceStart = fallbackStart;
              replaceEnd = fallbackStart + selectedText.length;
            }

            const nextContent = currentContent.substring(0, replaceStart) + aiText + currentContent.substring(replaceEnd);
            targetForm.setFieldsValue({ content: nextContent });
          }
        );
      },
    });
  };

  const handleOpenModal = (id: string) => {
    const chapter = chapters.find(c => c.id === id);
    if (chapter) {
      form.setFieldsValue(chapter);
      setEditingId(id);
      setIsModalOpen(true);
    }
  };

  const handleSubmit = async (values: ChapterUpdate) => {
    if (!editingId) return;

    try {
      await updateChapter(editingId, values);

      // 刷新章节列表以获取完整的章节数据（包括outline_title等联查字段）
      await refreshChapters();

      message.success('章节更新成功');
      setIsModalOpen(false);
      form.resetFields();
    } catch {
      message.error('操作失败');
    }
  };

  const handleOpenEditor = (id: string) => {
    const chapter = chapters.find(c => c.id === id);
    if (chapter) {
      setCurrentChapter(chapter);
      editorForm.setFieldsValue({
        title: chapter.title,
        summary: chapter.summary,
        content: chapter.content,
      });
      setEditingId(id);
      setTemporaryNarrativePerspective(undefined); // 重置人称选择
      setIsEditorOpen(true);
      // 打开编辑窗口时加载模型列表
      loadAvailableModels();
    }
  };

  const handleEditorSubmit = async (values: ChapterUpdate) => {
    if (!editingId || !currentProject) return;

    try {
      await updateChapter(editingId, values);

      // 刷新项目信息以更新总字数统计
      const updatedProject = await projectApi.getProject(currentProject.id);
      setCurrentProject(updatedProject);

      message.success('章节保存成功');
      setIsEditorOpen(false);
    } catch {
      message.error('保存失败');
    }
  };

  const handleGenerate = async () => {
    if (!editingId) return;

    try {
      setIsContinuing(true);
      setIsGenerating(true);
      setSingleChapterProgress(0);
      setSingleChapterProgressMessage('准备开始生成...');

      const result = await generateChapterContentStream(
        editingId,
        (content) => {
          editorForm.setFieldsValue({ content });

          if (contentTextAreaRef.current) {
            const textArea = contentTextAreaRef.current.resizableTextArea?.textArea;
            if (textArea) {
              textArea.scrollTop = textArea.scrollHeight;
            }
          }
        },
        selectedStyleId,
        targetWordCount,
        (progressMsg, progressValue) => {
          // 进度回调
          setSingleChapterProgress(progressValue);
          setSingleChapterProgressMessage(progressMsg);
        },
        selectedModel,  // 传递选中的模型
        temporaryNarrativePerspective  // 传递临时人称参数
      );

      message.success('AI创作成功，正在分析章节内容...');

      // 如果返回了分析任务ID，启动轮询
      if (result?.analysis_task_id) {
        const taskId = result.analysis_task_id;
        setAnalysisTasksMap(prev => ({
          ...prev,
          [editingId]: {
            has_task: true,
            task_id: taskId,
            chapter_id: editingId,
            status: 'pending',
            progress: 0
          }
        }));

        // 启动轮询
        startPollingTask(editingId);
      }
    } catch (error) {
      const apiError = error as ApiError;
      message.error('AI创作失败：' + (apiError.response?.data?.detail || apiError.message || '未知错误'));
    } finally {
      setIsContinuing(false);
      setIsGenerating(false);
      setSingleChapterProgress(0);
      setSingleChapterProgressMessage('');
    }
  };

  const showGenerateModal = (chapter: Chapter) => {
    const previousChapters = chapters.filter(
      c => c.chapter_number < chapter.chapter_number
    ).sort((a, b) => a.chapter_number - b.chapter_number);

    const selectedStyle = writingStyles.find(s => s.id === selectedStyleId);

    const instance = modal.confirm({
      title: 'AI创作章节内容',
      width: 700,
      centered: true,
      content: (
        <div style={{ marginTop: 16 }}>
          <p>AI将根据以下信息创作本章内容：</p>
          <ul>
            <li>章节大纲和要求</li>
            <li>项目的世界观设定</li>
            <li>相关角色信息</li>
            <li><strong>前面已完成章节的内容（确保剧情连贯）</strong></li>
            {selectedStyle && (
              <li><strong>写作风格：{selectedStyle.name}</strong></li>
            )}
            <li><strong>目标字数：{targetWordCount}字</strong></li>
          </ul>

          {previousChapters.length > 0 && (
            <div style={{
              marginTop: 16,
              padding: 12,
              background: token.colorInfoBg,
              borderRadius: token.borderRadius,
              border: `1px solid ${token.colorInfoBorder}`
            }}>
              <div style={{ marginBottom: 8, fontWeight: 500, color: token.colorPrimary }}>
                📚 将引用的前置章节（共{previousChapters.length}章）：
              </div>
              <div style={{ maxHeight: 150, overflowY: 'auto' }}>
                {previousChapters.map(ch => (
                  <div key={ch.id} style={{ padding: '4px 0', fontSize: 13 }}>
                    ✓ 第{ch.chapter_number}章：{ch.title} ({ch.word_count || 0}字)
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 8, fontSize: 12, color: token.colorTextSecondary }}>
                💡 AI会参考这些章节内容，确保情节连贯、角色状态一致
              </div>
            </div>
          )}

          <p style={{ color: token.colorError, marginTop: 16, marginBottom: 0 }}>
            ⚠️ 注意：此操作将覆盖当前章节内容
          </p>
        </div>
      ),
      okText: '开始创作',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        instance.update({
          okButtonProps: { danger: true, loading: true },
          cancelButtonProps: { disabled: true },
          closable: false,
          maskClosable: false,
          keyboard: false,
        });

        try {
          if (!selectedStyleId) {
            message.error('请先选择写作风格');
            instance.update({
              okButtonProps: { danger: true, loading: false },
              cancelButtonProps: { disabled: false },
              closable: true,
              maskClosable: true,
              keyboard: true,
            });
            return;
          }
          await handleGenerate();
          instance.destroy();
        } catch {
          instance.update({
            okButtonProps: { danger: true, loading: false },
            cancelButtonProps: { disabled: false },
            closable: true,
            maskClosable: true,
            keyboard: true,
          });
        }
      },
      onCancel: () => {
        if (isGenerating) {
          message.warning('AI正在创作中，请等待完成');
          return false;
        }
      },
    });
  };


  // 后台生成章节（关闭浏览器也不影响）
  // 不再强制显示进度弹窗，任务进度在右下角悬浮任务框中显示
  const handleBackgroundGenerate = async () => {
    if (!editingId) return;
    if (!selectedStyleId) {
      message.error("请先选择写作风格");
      return;
    }

    try {
      await generateChapterBackground(
        editingId,
        {
          style_id: selectedStyleId,
          target_word_count: targetWordCount,
          model: selectedModel,
          narrative_perspective: temporaryNarrativePerspective,
        },
        () => {
          // 进度更新由悬浮任务框处理，无需额外操作
        },
        () => {
          message.success("后台章节生成完成！");
          refreshChapters();
          if (currentProject) {
            projectApi.getProject(currentProject.id).then(setCurrentProject).catch(console.error);
          }
          loadAnalysisTasks();
        },
        (error) => {
          message.error("后台生成失败: " + error);
        }
      );

      message.info("章节生成任务已提交，可在右下角任务面板查看进度");
      // 通知悬浮任务框刷新
      eventBus.emit('background-task-created');
    } catch {
      message.error("创建后台任务失败");
    }
  };
  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      'draft': 'default',
      'pending': 'warning',
      'writing': 'processing',
      'completed': 'success',
    };
    return colors[status] || 'default';
  };

  const getStatusText = (status: string) => {
    const texts: Record<string, string> = {
      'draft': '草稿',
      'pending': '待处理',
      'writing': '创作中',
      'completed': '已完成',
    };
    return texts[status] || status;
  };

  const handleExport = () => {
    if (chapters.length === 0) {
      message.warning('当前项目没有章节，无法导出');
      return;
    }

    const firstChapter = sortedChapters[0]?.chapter_number || 1;
    const lastChapter = sortedChapters[sortedChapters.length - 1]?.chapter_number || firstChapter;
    setExportRangeType('all');
    exportForm.setFieldsValue({
      rangeType: 'all',
      start_chapter: firstChapter,
      end_chapter: lastChapter,
      exportMode: 'merged',
    });
    setExportModalVisible(true);
  };

  const handleExportSubmit = async () => {
    try {
      const values = await exportForm.validateFields();
      const startChapter = Number(values.start_chapter);
      const endChapter = Number(values.end_chapter);

      if (values.rangeType === 'custom' && startChapter > endChapter) {
        message.warning('起始章节不能大于结束章节');
        return;
      }

      setExporting(true);
      await projectApi.exportProject(currentProject.id, {
        start_chapter: values.rangeType === 'custom' ? startChapter : undefined,
        end_chapter: values.rangeType === 'custom' ? endChapter : undefined,
        split: values.exportMode === 'split',
      });
      setExportModalVisible(false);
      message.success(values.exportMode === 'split' ? '开始下载分章ZIP' : '开始下载TXT文件');
    } catch (error) {
      if (isAntdValidationError(error)) {
        return;
      }
      if (error instanceof Error && error.message) {
        message.error(`导出失败：${error.message}`);
      } else if (error) {
        message.error('导出失败，请重试');
      }
    } finally {
      setExporting(false);
    }
  };

  const getNextChapterNumber = () => (
    chapters.length > 0
      ? Math.max(...chapters.map(c => c.chapter_number)) + 1
      : 1
  );

  const handleOpenImportModal = () => {
    const nextChapterNumber = getNextChapterNumber();
    setImportMode('auto_split');
    setImportPosition('append');
    setImportFileList([]);
    importForm.setFieldsValue({
      import_mode: 'auto_split',
      import_position: 'append',
      start_chapter_number: nextChapterNumber,
      conflict_strategy: 'skip',
      status: 'draft',
    });
    setImportModalVisible(true);
  };

  const handleImportSubmit = async () => {
    try {
      const values = await importForm.validateFields();
      const files = importFileList
        .map(file => file.originFileObj)
        .filter(Boolean) as File[];

      if (files.length === 0) {
        message.warning('请先选择要导入的 TXT 或 Markdown 文件');
        return;
      }

      const formData = new FormData();
      files.forEach(file => formData.append('files', file));
      formData.append('import_mode', values.import_mode);
      formData.append('status', values.status || 'draft');
      formData.append(
        'conflict_strategy',
        values.import_position === 'custom' ? (values.conflict_strategy || 'skip') : 'skip'
      );
      if (values.import_position === 'custom' && values.start_chapter_number) {
        formData.append('start_chapter_number', String(values.start_chapter_number));
      }

      setImporting(true);
      const result = await chapterApi.importChapters(currentProject.id, formData);
      await refreshChapters();
      const updatedProject = await projectApi.getProject(currentProject.id);
      setCurrentProject(updatedProject);

      const importSummary = `新增 ${result.imported} 章，覆盖 ${result.updated} 章，跳过 ${result.skipped} 章`;
      if (result.warnings?.length) {
        modal.success({
          title: '导入完成',
          width: 620,
          content: (
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <div>{importSummary}</div>
              <Alert
                type="info"
                showIcon
                message="章节切分诊断"
                description={
                  <List
                    size="small"
                    dataSource={result.warnings}
                    renderItem={(warning) => <List.Item>{warning}</List.Item>}
                  />
                }
              />
            </Space>
          ),
        });
      } else {
        message.success(`导入完成：${importSummary}`);
      }
      setImportModalVisible(false);
      setImportFileList([]);
      importForm.resetFields();
    } catch (error) {
      if (isAntdValidationError(error)) {
        return;
      }
      const err = error as Error;
      message.error(`导入失败：${err.message || '未知错误'}`);
    } finally {
      setImporting(false);
    }
  };

  const handleShowAnalysis = (chapterId: string) => {
    setAnalysisChapterId(chapterId);
    setAnalysisVisible(true);
  };

  // 一键按章节顺序分析未分析章节
  const handleBatchAnalyzeUnanalyzed = async () => {
    if (!currentProject?.id) return;

    try {
      setBatchAnalyzingUnanalyzed(true);
      const result = await chapterApi.batchAnalyzeUnanalyzed(currentProject.id);

      if (result.total_started > 0) {
        setAnalysisTasksMap((prev) => ({
          ...prev,
          ...result.started_tasks,
        }));

        Object.keys(result.started_tasks).forEach((chapterId) => {
          startPollingTask(chapterId);
        });

        message.success(
          `已加入 ${result.total_started} 章顺序分析队列（跳过已分析 ${result.total_already_completed} 章，分析中/排队中 ${result.total_skipped_running} 章）`
        );
      } else {
        message.info('没有可启动分析的章节：当前章节要么无内容、要么已分析完成、要么正在分析中');
      }

      // 刷新一次状态，确保前端与后端一致
      await loadAnalysisTasks();
    } catch (error: unknown) {
      const err = error as Error;
      message.error(`一键分析失败：${err.message || '未知错误'}`);
    } finally {
      setBatchAnalyzingUnanalyzed(false);
    }
  };

  // 批量生成函数
  const handleBatchGenerate = async (values: {
    startChapterNumber: number;
    count: number;
    enableAnalysis: boolean;
    styleId?: number;
    targetWordCount?: number;
    model?: string;
  }) => {
    if (!currentProject?.id) return;

    // 调试日志
    console.log('[批量生成] 表单values:', values);
    console.log('[批量生成] batchSelectedModel状态:', batchSelectedModel);

    // 使用批量生成对话框中选择的风格和字数，如果没有选择则使用默认值
    const styleId = values.styleId || selectedStyleId;
    const wordCount = values.targetWordCount || targetWordCount;

    // 使用批量生成专用的模型状态
    const model = batchSelectedModel;

    console.log('[批量生成] 最终使用的model:', model);

    if (!styleId) {
      message.error('请选择写作风格');
      return;
    }

    try {
      setBatchGenerating(true);
      setBatchGenerateVisible(false); // 关闭配置对话框，任务进度在悬浮任务框中显示

      const requestBody: {
        start_chapter_number: number;
        count: number;
        enable_analysis: boolean;
        style_id: number;
        target_word_count: number;
        model?: string;
      } = {
        start_chapter_number: values.startChapterNumber,
        count: values.count,
        enable_analysis: true,
        style_id: styleId,
        target_word_count: wordCount,
      };

      // 如果有模型参数，添加到请求体中
      if (model) {
        requestBody.model = model;
        console.log('[批量生成] 请求体包含model:', model);
      } else {
        console.log('[批量生成] 请求体不包含model，使用后端默认模型');
      }

      console.log('[批量生成] 完整请求体:', JSON.stringify(requestBody, null, 2));

      const response = await fetch(`/api/chapters/project/${currentProject.id}/batch-generate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || '创建批量生成任务失败');
      }

      const result = await response.json();
      setBatchTaskId(result.batch_id);
      setBatchProgress({
        status: 'running',
        total: result.chapters_to_generate.length,
        completed: 0,
        current_chapter_number: values.startChapterNumber,
        estimated_time_minutes: result.estimated_time_minutes,
      });

      message.success(`批量生成任务已创建，预计需要 ${result.estimated_time_minutes} 分钟，可在右下角任务面板查看进度`);
      // 通知悬浮任务框刷新
      eventBus.emit('background-task-created');

      // 🔔 触发浏览器通知（任务开始）
      showBrowserNotification(
        '批量生成已启动',
        `开始生成 ${result.chapters_to_generate.length} 章，预计需要 ${result.estimated_time_minutes} 分钟`,
        'info'
      );

      // 开始轮询任务状态
      startBatchPolling(result.batch_id);

    } catch (error: unknown) {
      const err = error as Error;
      message.error('创建批量生成任务失败：' + (err.message || '未知错误'));
      setBatchGenerating(false);
      setBatchGenerateVisible(false);
    }
  };

  // 轮询批量生成任务状态
  const startBatchPolling = (taskId: string) => {
    if (batchPollingIntervalRef.current) {
      clearInterval(batchPollingIntervalRef.current);
    }

    const poll = async () => {
      try {
        const response = await fetch(`/api/chapters/batch-generate/${taskId}/status`);
        if (!response.ok) return;

        const status = await response.json();
        setBatchProgress({
          status: status.status,
          total: status.total,
          completed: status.completed,
          current_chapter_number: status.current_chapter_number,
        });

        // 每次轮询时刷新章节列表和分析状态，实时显示新生成的章节和分析进度
        // 使用 await 确保获取最新章节列表后再加载分析任务状态
        if (status.completed > 0) {
          const latestChapters = await refreshChapters();
          await loadAnalysisTasks(latestChapters);

          // 刷新项目信息以实时更新总字数统计
          if (currentProject?.id) {
            const updatedProject = await projectApi.getProject(currentProject.id);
            setCurrentProject(updatedProject);
          }
        }

        // 任务完成或失败，停止轮询
        if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') {
          if (batchPollingIntervalRef.current) {
            clearInterval(batchPollingIntervalRef.current);
            batchPollingIntervalRef.current = null;
          }

          setBatchGenerating(false);

          // 立即刷新章节列表和分析任务状态（在显示消息前）
          // 使用 refreshChapters 返回的最新章节列表传递给 loadAnalysisTasks
          const finalChapters = await refreshChapters();
          await loadAnalysisTasks(finalChapters);

          // 刷新项目信息以更新总字数统计
          if (currentProject?.id) {
            const updatedProject = await projectApi.getProject(currentProject.id);
            setCurrentProject(updatedProject);
          }

          if (status.status === 'completed') {
            message.success(`批量生成完成！成功生成 ${status.completed} 章`);
            // 🔔 触发浏览器通知
            showBrowserNotification(
              '批量生成完成',
              `《${currentProject?.title || '项目'}》成功生成 ${status.completed} 章节`,
              'success'
            );
          } else if (status.status === 'failed') {
            message.error(`批量生成失败：${status.error_message || '未知错误'}`);
            // 🔔 触发浏览器通知
            showBrowserNotification(
              '批量生成失败',
              status.error_message || '未知错误',
              'error'
            );
          } else if (status.status === 'cancelled') {
            message.warning('批量生成已取消');
          }

          // 延迟关闭对话框，让用户看到最终状态
          setTimeout(() => {
            setBatchGenerateVisible(false);
            setBatchTaskId(null);
            setBatchProgress(null);
          }, 2000);
        }
      } catch (error) {
        console.error('轮询批量生成状态失败:', error);
      }
    };

    // 立即执行一次
    poll();

    // 每2秒轮询一次
    batchPollingIntervalRef.current = window.setInterval(poll, 2000);
  };

  // 取消批量生成
  const handleCancelBatchGenerate = async () => {
    if (!batchTaskId) return;

    try {
      const response = await fetch(`/api/chapters/batch-generate/${batchTaskId}/cancel`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error('取消失败');
      }

      message.success('批量生成已取消');

      // 取消后立即刷新章节列表和分析任务，显示已生成的章节
      await refreshChapters();
      await loadAnalysisTasks();

      // 刷新项目信息以更新总字数统计
      if (currentProject?.id) {
        const updatedProject = await projectApi.getProject(currentProject.id);
        setCurrentProject(updatedProject);
      }
    } catch (error: unknown) {
      const err = error as Error;
      message.error('取消失败：' + (err.message || '未知错误'));
    }
  };

  // 打开批量生成对话框
  const handleOpenBatchGenerate = async () => {
    // 找到第一个未生成的章节
    const firstIncompleteChapter = sortedChapters.find(
      ch => !ch.content || ch.content.trim() === ''
    );

    if (!firstIncompleteChapter) {
      message.info('所有章节都已生成内容');
      return;
    }

    // 检查该章节是否可以生成
    if (!canGenerateChapter(firstIncompleteChapter)) {
      const reason = getGenerateDisabledReason(firstIncompleteChapter);
      message.warning(reason);
      return;
    }

    // 打开对话框时加载模型列表，等待完成
    const defaultModel = await loadAvailableModels();

    console.log('[打开批量生成] defaultModel:', defaultModel);
    console.log('[打开批量生成] selectedStyleId:', selectedStyleId);

    // 设置批量生成的模型选择状态
    setBatchSelectedModel(defaultModel || undefined);

    // 重置表单并设置初始值（使用缓存的字数）
    batchForm.setFieldsValue({
      startChapterNumber: firstIncompleteChapter.chapter_number,
      count: 5,
      enableAnalysis: false,
      styleId: selectedStyleId,
      targetWordCount: getCachedWordCount(),
    });

    setBatchGenerateVisible(true);
  };

  // 手动新建章节，支持直接粘贴正文
  const showManualCreateChapterModal = () => {
    const nextChapterNumber = getNextChapterNumber();
    manualCreateForm.resetFields();
    manualCreateForm.setFieldsValue({
      chapter_number: nextChapterNumber,
      status: 'draft',
    });

    modal.confirm({
      title: '新建章节',
      width: isMobile ? 'calc(100vw - 32px)' : 720,
      centered: true,
      content: (
        <Form
          form={manualCreateForm}
          layout="vertical"
          style={{ marginTop: 16 }}
        >
          <Form.Item
            label="章节序号"
            name="chapter_number"
            rules={[{ required: true, message: '请输入章节序号' }]}
            tooltip="建议按顺序创建章节，确保内容连贯性"
          >
            <InputNumber min={1} style={{ width: '100%' }} placeholder="自动计算的下一个序号" />
          </Form.Item>

          <Form.Item
            label="章节标题"
            required
          >
            <Space.Compact style={{ width: '100%' }}>
              <Form.Item
                name="title"
                noStyle
                rules={[{ required: true, message: '请输入标题' }]}
              >
                <Input placeholder="例如：第一章 初遇" />
              </Form.Item>
              <Button
                icon={<ThunderboltOutlined />}
                onClick={() => openChapterAiTool(manualCreateForm, 'title', '章节标题', 'generate_title')}
              >
                AI生成
              </Button>
              <Button
                icon={<HighlightOutlined />}
                onClick={() => openChapterAiTool(manualCreateForm, 'title', '章节标题', 'polish')}
              >
                润色
              </Button>
            </Space.Compact>
          </Form.Item>

          <Form.Item
            label="关联大纲"
            name="outline_id"
            tooltip="可选。不关联大纲时会作为独立章节保存。"
          >
            <Select allowClear placeholder="可选：选择所属大纲">
              {/* 直接使用 store 中的 outlines 数据，而不是从现有章节中提取 */}
              {[...outlines]
                .sort((a, b) => a.order_index - b.order_index)
                .map(outline => (
                  <Select.Option key={outline.id} value={outline.id}>
                    第{outline.order_index}卷：{outline.title}
                  </Select.Option>
                ))}
            </Select>
          </Form.Item>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <span style={{ color: token.colorTextSecondary }}>章节正文</span>
            <Space wrap size={8}>
              <Button
                size="small"
                icon={<HighlightOutlined />}
                onClick={() => openChapterAiTool(manualCreateForm, 'content', '章节正文', 'polish')}
              >
                润色全文
              </Button>
              <Button
                size="small"
                icon={<ThunderboltOutlined />}
                onClick={() => openChapterAiTool(manualCreateForm, 'content', '章节正文', 'rewrite')}
              >
                重写全文
              </Button>
              <Button
                size="small"
                icon={<EditOutlined />}
                onClick={() => openSelectedContentAiTool(manualCreateForm, manualContentTextAreaRef)}
              >
                选中编辑
              </Button>
            </Space>
          </div>

          <Form.Item
            name="content"
            tooltip="可以直接从外部文档复制粘贴整章正文"
          >
            <TextArea
              ref={manualContentTextAreaRef}
              rows={10}
              placeholder="粘贴或输入章节正文..."
              showCount
            />
          </Form.Item>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <span style={{ color: token.colorTextSecondary }}>章节摘要（可选）</span>
            <Space wrap size={8}>
              <Button
                size="small"
                icon={<ThunderboltOutlined />}
                onClick={() => openChapterAiTool(manualCreateForm, 'summary', '章节摘要', 'generate_summary')}
              >
                AI生成
              </Button>
              <Button
                size="small"
                icon={<HighlightOutlined />}
                onClick={() => openChapterAiTool(manualCreateForm, 'summary', '章节摘要', 'polish')}
              >
                润色
              </Button>
            </Space>
          </div>

          <Form.Item
            name="summary"
            tooltip="简要描述本章的主要内容和情节发展"
          >
            <TextArea
              rows={4}
              placeholder="简要描述本章内容..."
            />
          </Form.Item>

          <Form.Item
            label="状态"
            name="status"
          >
            <Select>
              <Select.Option value="draft">草稿</Select.Option>
              <Select.Option value="pending">待处理</Select.Option>
              <Select.Option value="writing">创作中</Select.Option>
              <Select.Option value="completed">已完成</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      ),
      okText: '创建',
      cancelText: '取消',
      onOk: async () => {
        const values = await manualCreateForm.validateFields();

        // 检查章节序号是否已存在
        const conflictChapter = chapters.find(
          ch => ch.chapter_number === values.chapter_number
        );

        if (conflictChapter) {
          // 显示冲突提示Modal
          modal.confirm({
            title: '章节序号冲突',
            icon: <InfoCircleOutlined style={{ color: token.colorError }} />,
            width: 500,
            centered: true,
            content: (
              <div>
                <p style={{ marginBottom: 12 }}>
                  第 <strong>{values.chapter_number}</strong> 章已存在：
                </p>
                <div style={{
                  padding: 12,
                  background: token.colorWarningBg,
                  borderRadius: token.borderRadius,
                  border: `1px solid ${token.colorWarningBorder}`,
                  marginBottom: 12
                }}>
                  <div><strong>标题：</strong>{conflictChapter.title}</div>
                  <div><strong>状态：</strong>{getStatusText(conflictChapter.status)}</div>
                  <div><strong>字数：</strong>{conflictChapter.word_count || 0}字</div>
                  {conflictChapter.outline_title && (
                    <div><strong>所属大纲：</strong>{conflictChapter.outline_title}</div>
                  )}
                </div>
                <p style={{ color: token.colorError, marginBottom: 8 }}>
                  ⚠️ 是否删除旧章节并创建新章节？
                </p>
                <p style={{ fontSize: 12, color: token.colorTextSecondary, marginBottom: 0 }}>
                  删除后将无法恢复，章节内容和分析结果都将被删除。
                </p>
              </div>
            ),
            okText: '删除并创建',
            okButtonProps: { danger: true },
            cancelText: '取消',
            onOk: async () => {
              try {
                // 先删除旧章节
                await handleDeleteChapter(conflictChapter.id);

                // 等待一小段时间确保删除完成
                await new Promise(resolve => setTimeout(resolve, 300));

                // 创建新章节
                await chapterApi.createChapter({
                  project_id: currentProject.id,
                  ...values
                });

                message.success('已删除旧章节并创建新章节');
                await refreshChapters();

                // 刷新项目信息以更新字数统计
                const updatedProject = await projectApi.getProject(currentProject.id);
                setCurrentProject(updatedProject);

                manualCreateForm.resetFields();
              } catch (error: unknown) {
                const err = error as Error;
                message.error('操作失败：' + (err.message || '未知错误'));
                throw error;
              }
            }
          });

          // 阻止外层Modal关闭
          return Promise.reject();
        }

        // 没有冲突，直接创建
        try {
          await chapterApi.createChapter({
            project_id: currentProject.id,
            ...values
          });
          message.success('章节创建成功');
          await refreshChapters();

          // 刷新项目信息以更新字数统计
          const updatedProject = await projectApi.getProject(currentProject.id);
          setCurrentProject(updatedProject);

          manualCreateForm.resetFields();
        } catch (error: unknown) {
          const err = error as Error;
          message.error('创建失败：' + (err.message || '未知错误'));
          throw error;
        }
      }
    });
  };

  // 渲染分析状态标签
  const renderAnalysisStatus = (chapterId: string) => {
    const task = analysisTasksMap[chapterId];

    if (!task) {
      return null;
    }

    switch (task.status) {
      case 'pending':
        return (
          <Tag icon={<SyncOutlined spin />} color="processing">
            等待分析
          </Tag>
        );
      case 'running': {
        // 检查是否正在重试（后端会在error_message中包含"重试"信息）
        const isRetrying = task.error_message && task.error_message.includes('重试');
        return (
          <Tag
            icon={<SyncOutlined spin />}
            color={isRetrying ? "warning" : "processing"}
            title={task.error_message || undefined}
          >
            {isRetrying ? `重试中 ${task.progress}%` : `分析中 ${task.progress}%`}
          </Tag>
        );
      }
      case 'completed':
        return (
          <Tag icon={<CheckCircleOutlined />} color="success">
            已分析
          </Tag>
        );
      case 'failed':
        return (
          <Tag icon={<CloseCircleOutlined />} color="error" title={task.error_message || undefined}>
            分析失败
          </Tag>
        );
      default:
        return null;
    }
  };

  // 显示展开规划详情
  const showExpansionPlanModal = (chapter: Chapter) => {
    if (!chapter.expansion_plan) return;

    try {
      const planData: ExpansionPlanData = JSON.parse(chapter.expansion_plan);

      modal.info({
        title: (
          <Space style={{ flexWrap: 'wrap' }}>
            <InfoCircleOutlined style={{ color: token.colorPrimary }} />
            <span style={{ wordBreak: 'break-word' }}>第{chapter.chapter_number}章展开规划</span>
          </Space>
        ),
        width: isMobile ? 'calc(100vw - 32px)' : 800,
        centered: true,
        style: isMobile ? {
          maxWidth: 'calc(100vw - 32px)',
          margin: '0 auto',
          padding: '0 16px'
        } : undefined,
        styles: {
          body: {
            maxHeight: isMobile ? 'calc(100vh - 200px)' : 'calc(80vh - 110px)',
            overflowY: 'auto'
          }
        },
        content: (
          <div style={{ marginTop: 16 }}>
            <Descriptions
              column={1}
              size="small"
              bordered
              labelStyle={{
                whiteSpace: 'normal',
                wordBreak: 'break-word',
                width: isMobile ? '80px' : '100px'
              }}
              contentStyle={{
                whiteSpace: 'normal',
                wordBreak: 'break-word',
                overflowWrap: 'break-word'
              }}
            >
              <Descriptions.Item label="章节标题">
                <strong style={{
                  wordBreak: 'break-word',
                  whiteSpace: 'normal',
                  overflowWrap: 'break-word'
                }}>
                  {chapter.title}
                </strong>
              </Descriptions.Item>
              <Descriptions.Item label="情感基调">
                <Tag
                  color="blue"
                  style={{
                    whiteSpace: 'normal',
                    wordBreak: 'break-word',
                    height: 'auto',
                    lineHeight: '1.5',
                    padding: '4px 8px'
                  }}
                >
                  {planData.emotional_tone}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="冲突类型">
                <Tag
                  color="orange"
                  style={{
                    whiteSpace: 'normal',
                    wordBreak: 'break-word',
                    height: 'auto',
                    lineHeight: '1.5',
                    padding: '4px 8px'
                  }}
                >
                  {planData.conflict_type}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="预估字数">
                <Tag color="green">{planData.estimated_words}字</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="叙事目标">
                <span style={{
                  wordBreak: 'break-word',
                  whiteSpace: 'normal',
                  overflowWrap: 'break-word'
                }}>
                  {planData.narrative_goal}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="关键事件">
                <Space direction="vertical" size="small" style={{ width: '100%' }}>
                  {planData.key_events.map((event, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: '4px 0',
                        wordBreak: 'break-word',
                        whiteSpace: 'normal',
                        overflowWrap: 'break-word'
                      }}
                    >
                      <Tag color="purple" style={{ flexShrink: 0 }}>{idx + 1}</Tag>{' '}
                      <span style={{
                        wordBreak: 'break-word',
                        whiteSpace: 'normal',
                        overflowWrap: 'break-word'
                      }}>
                        {event}
                      </span>
                    </div>
                  ))}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="涉及角色">
                <Space wrap style={{ maxWidth: '100%' }}>
                  {planData.character_focus.map((char, idx) => (
                    <Tag
                      key={idx}
                      color="cyan"
                      style={{
                        whiteSpace: 'normal',
                        wordBreak: 'break-word',
                        height: 'auto',
                        lineHeight: '1.5'
                      }}
                    >
                      {char}
                    </Tag>
                  ))}
                </Space>
              </Descriptions.Item>
              {planData.scenes && planData.scenes.length > 0 && (
                <Descriptions.Item label="场景规划">
                  <Space direction="vertical" size="small" style={{ width: '100%' }}>
                    {planData.scenes.map((scene, idx) => (
                      <Card
                        key={idx}
                        size="small"
                        style={{
                          backgroundColor: token.colorFillQuaternary,
                          maxWidth: '100%',
                          overflow: 'hidden'
                        }}
                      >
                        <div style={{
                          marginBottom: 4,
                          wordBreak: 'break-word',
                          whiteSpace: 'normal',
                          overflowWrap: 'break-word'
                        }}>
                          <strong>📍 地点：</strong>
                          <span style={{
                            wordBreak: 'break-word',
                            whiteSpace: 'normal',
                            overflowWrap: 'break-word'
                          }}>
                            {scene.location}
                          </span>
                        </div>
                        <div style={{ marginBottom: 4 }}>
                          <strong>👥 角色：</strong>
                          <Space
                            size="small"
                            wrap
                            style={{
                              marginLeft: isMobile ? 0 : 8,
                              marginTop: isMobile ? 4 : 0,
                              display: isMobile ? 'flex' : 'inline-flex'
                            }}
                          >
                            {scene.characters.map((char, charIdx) => (
                              <Tag
                                key={charIdx}
                                style={{
                                  whiteSpace: 'normal',
                                  wordBreak: 'break-word',
                                  height: 'auto'
                                }}
                              >
                                {char}
                              </Tag>
                            ))}
                          </Space>
                        </div>
                        <div style={{
                          wordBreak: 'break-word',
                          whiteSpace: 'normal',
                          overflowWrap: 'break-word'
                        }}>
                          <strong>🎯 目的：</strong>
                          <span style={{
                            wordBreak: 'break-word',
                            whiteSpace: 'normal',
                            overflowWrap: 'break-word'
                          }}>
                            {scene.purpose}
                          </span>
                        </div>
                      </Card>
                    ))}
                  </Space>
                </Descriptions.Item>
              )}
            </Descriptions>
            <Alert
              message="提示"
              description="这些是AI在大纲展开时生成的规划信息，可以作为创作章节内容时的参考。"
              type="info"
              showIcon
              style={{ marginTop: 16 }}
            />
          </div>
        ),
        okText: '关闭',
      });
    } catch (error) {
      console.error('解析展开规划失败:', error);
      message.error('展开规划数据格式错误');
    }
  };

  // 删除章节处理函数
  const handleDeleteChapter = async (chapterId: string) => {
    try {
      await deleteChapter(chapterId);

      // 刷新章节列表
      await refreshChapters();

      // 刷新项目信息以更新总字数统计
      if (currentProject) {
        const updatedProject = await projectApi.getProject(currentProject.id);
        setCurrentProject(updatedProject);
      }

      message.success('章节删除成功');
    } catch (error: unknown) {
      const err = error as Error;
      message.error('删除章节失败：' + (err.message || '未知错误'));
    }
  };

  // 打开规划编辑器
  const handleOpenPlanEditor = (chapter: Chapter) => {
    // 直接打开编辑器,如果没有规划数据则创建新的
    setEditingPlanChapter(chapter);
    setPlanEditorVisible(true);
  };

  // 保存规划信息
  const handleSavePlan = async (planData: ExpansionPlanData) => {
    if (!editingPlanChapter) return;

    try {
      const response = await fetch(`/api/chapters/${editingPlanChapter.id}/expansion-plan`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(planData),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || '更新失败');
      }

      // 刷新章节列表
      await refreshChapters();

      message.success('规划信息更新成功');

      // 关闭编辑器
      setPlanEditorVisible(false);
      setEditingPlanChapter(null);
    } catch (error: unknown) {
      const err = error as Error;
      message.error('保存规划失败：' + (err.message || '未知错误'));
      throw error;
    }
  };

  // 打开阅读器
  const handleOpenReader = (chapter: Chapter) => {
    setReadingChapter(chapter);
    setReaderVisible(true);
  };

  // 阅读器切换章节
  const handleReaderChapterChange = async (chapterId: string) => {
    try {
      const response = await fetch(`/api/chapters/${chapterId}`);
      if (!response.ok) throw new Error('获取章节失败');
      const newChapter = await response.json();
      setReadingChapter(newChapter);
    } catch {
      message.error('加载章节失败');
    }
  };

  // 打开局部重写弹窗
  const handleOpenPartialRegenerate = () => {
    setPartialRegenerateToolbarVisible(false);
    setPartialRegenerateTitle('AI精准重写选中段落');
    setPartialRegenerateModalVisible(true);
  };

  const handleOpenSelectedTextRegenerate = () => {
    const textArea = contentTextAreaRef.current?.resizableTextArea?.textArea;
    if (!textArea) {
      message.warning('请先打开章节内容编辑器');
      return;
    }

    const start = textArea.selectionStart;
    const end = textArea.selectionEnd;
    const selectedText = textArea.value.substring(start, end);

    if (start === end || selectedText.trim().length < 10) {
      message.warning('请先在章节内容中选中至少10个字');
      return;
    }

    setSelectedTextForRegenerate(selectedText);
    setSelectionStartPosition(start);
    setSelectionEndPosition(end);
    setPartialRegenerateToolbarVisible(false);
    setPartialRegenerateTitle('AI精准重写选中段落');
    setPartialRegenerateModalVisible(true);
  };

  const handleOpenFullChapterRegenerate = () => {
    const content = String(editorForm.getFieldValue('content') || '');
    if (!content.trim()) {
      message.warning('章节内容为空，无法重写');
      return;
    }

    setSelectedTextForRegenerate(content);
    setSelectionStartPosition(0);
    setSelectionEndPosition(content.length);
    setPartialRegenerateToolbarVisible(false);
    setPartialRegenerateTitle('AI提示词重写整章');
    setPartialRegenerateModalVisible(true);
  };

  // 应用局部重写结果
  const handleApplyPartialRegenerate = (newText: string, startPos: number, endPos: number) => {
    // 获取当前内容
    const currentContent = editorForm.getFieldValue('content') || '';
    
    // 替换选中部分
    const newContent = currentContent.substring(0, startPos) + newText + currentContent.substring(endPos);
    
    // 更新表单
    editorForm.setFieldsValue({ content: newContent });
    
    // 关闭弹窗
    setPartialRegenerateModalVisible(false);
    
    message.success('局部重写已应用');
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {contextHolder}
      <div style={{
        position: 'sticky',
        top: 0,
        zIndex: 10,
        backgroundColor: token.colorBgContainer,
        padding: isMobile ? '12px 0' : '16px 0',
        marginBottom: isMobile ? 12 : 16,
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
        display: 'flex',
        flexDirection: isMobile ? 'column' : 'row',
        gap: isMobile ? 12 : 16,
        justifyContent: 'space-between',
        alignItems: isMobile ? 'stretch' : 'flex-start'
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <h2 style={{ margin: 0, fontSize: isMobile ? 18 : 24 }}>
            <BookOutlined style={{ marginRight: 8 }} />
            章节管理
          </h2>
          <Tag
            color={currentProject.outline_mode === 'one-to-one' ? 'blue' : 'green'}
            style={{ width: 'fit-content' }}
          >
            {currentProject.outline_mode === 'one-to-one'
              ? '传统模式：章节由大纲管理，请在大纲页面操作'
              : '细化模式：章节可在大纲页面展开'}
          </Tag>
        </div>
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: isMobile ? 'stretch' : 'flex-end',
          gap: 8,
          width: isMobile ? '100%' : 'auto',
          minWidth: isMobile ? 0 : 520,
        }}>
          <Space
            wrap
            size={8}
            style={{
              width: '100%',
              justifyContent: isMobile ? 'flex-start' : 'flex-end',
              alignItems: 'center',
            }}
          >
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder="搜索章节（序号/标题/大纲）"
              value={chapterSearchKeyword}
              onChange={(e) => setChapterSearchKeyword(e.target.value)}
              style={{ width: isMobile ? '100%' : 300 }}
            />
            <Button
              icon={<PlusOutlined />}
              onClick={showManualCreateChapterModal}
              block={isMobile}
            >
              新建章节
            </Button>
            <Button
              icon={<UploadOutlined />}
              onClick={handleOpenImportModal}
              block={isMobile}
            >
              导入章节
            </Button>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={handleBatchAnalyzeUnanalyzed}
              loading={batchAnalyzingUnanalyzed}
              disabled={chapters.length === 0 || batchAnalyzableChapterCount === 0}
              block={isMobile}
              style={{ background: token.colorWarning, borderColor: token.colorWarning }}
              title={batchAnalyzableChapterCount === 0 ? '暂无可一键分析章节' : `可一键分析 ${batchAnalyzableChapterCount} 章`}
            >
              一键分析{batchAnalyzableChapterCount > 0 ? ` (${batchAnalyzableChapterCount})` : ''}
            </Button>
            <Button
              type="primary"
              icon={<RocketOutlined />}
              onClick={handleOpenBatchGenerate}
              disabled={chapters.length === 0 || batchGenerating}
              loading={batchGenerating}
              block={isMobile}
              style={batchGenerating ? {} : { background: token.colorInfo, borderColor: token.colorInfo }}
            >
              {batchGenerating ? '生成中...' : '批量生成'}
            </Button>
            <Button
              type="default"
              icon={<DownloadOutlined />}
              onClick={handleExport}
              disabled={chapters.length === 0}
              block={isMobile}
            >
              导出章节
            </Button>
          </Space>
          <Space
            wrap
            size={8}
            style={{
              width: '100%',
              justifyContent: isMobile ? 'flex-start' : 'flex-end',
              alignItems: 'center',
            }}
          >
            <Select
              value={chapterStatusFilter}
              onChange={setChapterStatusFilter}
              style={{ width: isMobile ? 'calc(50% - 4px)' : 116 }}
              suffixIcon={<FilterOutlined />}
              options={[
                { value: 'all', label: '全部状态' },
                { value: 'draft', label: '草稿' },
                { value: 'pending', label: '待处理' },
                { value: 'writing', label: '创作中' },
                { value: 'completed', label: '已完成' },
              ]}
            />
            <Select
              value={chapterAnalysisFilter}
              onChange={setChapterAnalysisFilter}
              style={{ width: isMobile ? 'calc(50% - 4px)' : 116 }}
              options={[
                { value: 'all', label: '全部分析' },
                { value: 'completed', label: '已分析' },
                { value: 'unanalyzed', label: '未分析' },
                { value: 'running', label: '分析中' },
                { value: 'failed', label: '分析失败' },
              ]}
            />
            <Select
              value={chapterContentFilter}
              onChange={setChapterContentFilter}
              style={{ width: isMobile ? 'calc(50% - 4px)' : 116 }}
              options={[
                { value: 'all', label: '全部正文' },
                { value: 'has_content', label: '有正文' },
                { value: 'empty', label: '空章节' },
              ]}
            />
            <Select
              value={chapterOutlineFilter}
              onChange={setChapterOutlineFilter}
              style={{ width: isMobile ? 'calc(50% - 4px)' : 168 }}
              options={[
                { value: 'all', label: '全部大纲' },
                ...chapterOutlineOptions,
              ]}
            />
            <Button
              icon={<ClearOutlined />}
              disabled={!hasActiveChapterFilters}
              onClick={() => {
                setChapterSearchKeyword('');
                setChapterStatusFilter('all');
                setChapterAnalysisFilter('all');
                setChapterContentFilter('all');
                setChapterOutlineFilter('all');
              }}
            >
              重置
            </Button>
          </Space>
        </div>
      </div>


      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {chapters.length === 0 ? (
          <Empty description="还没有章节，开始创作吧！" />
        ) : filteredSortedChapters.length === 0 ? (
          <Empty description="未找到匹配章节" />
        ) : currentProject.outline_mode === 'one-to-one' ? (
          // one-to-one 模式：直接显示扁平列表
          <List
            dataSource={pagedSortedChapters}
            renderItem={(item) => (
              <List.Item
                id={`chapter-item-${item.id}`}
                style={{
                  padding: '16px',
                  marginBottom: 16,
                  background: token.colorBgContainer,
                  borderRadius: token.borderRadius,
                  border: `1px solid ${token.colorBorderSecondary}`,
                  flexDirection: isMobile ? 'column' : 'row',
                  alignItems: isMobile ? 'flex-start' : 'center',
                }}
                actions={isMobile ? undefined : [
                  <Button
                    type="text"
                    icon={<ReadOutlined />}
                    onClick={() => handleOpenReader(item)}
                    disabled={!item.content || item.content.trim() === ''}
                    title={!item.content || item.content.trim() === '' ? '暂无内容' : '沉浸式阅读'}
                  >
                    阅读
                  </Button>,
                  <Button
                    type="text"
                    icon={<EditOutlined />}
                    onClick={() => handleOpenEditor(item.id)}
                  >
                    编辑
                  </Button>,
                  (() => {
                    const task = analysisTasksMap[item.id];
                    const isAnalyzing = task && (task.status === 'pending' || task.status === 'running');
                    const hasContent = item.content && item.content.trim() !== '';

                    return (
                      <Button
                        type="text"
                        icon={isAnalyzing ? <SyncOutlined spin /> : <FundOutlined />}
                        onClick={() => handleShowAnalysis(item.id)}
                        disabled={!hasContent || isAnalyzing}
                        loading={isAnalyzing}
                        title={
                          !hasContent ? '请先生成章节内容' :
                            isAnalyzing ? '分析进行中，请稍候...' :
                              ''
                        }
                      >
                        {isAnalyzing ? '分析中' : '分析'}
                      </Button>
                    );
                  })(),
                  <Button
                    type="text"
                    icon={<SettingOutlined />}
                    onClick={() => handleOpenModal(item.id)}
                  >
                    修改
                  </Button>,
                ]}
              >
                <div style={{ width: '100%' }}>
                  <List.Item.Meta
                    avatar={!isMobile && <FileTextOutlined style={{ fontSize: 32, color: token.colorPrimary }} />}
                    title={
                      <div style={{
                        display: 'flex',
                        flexDirection: isMobile ? 'column' : 'row',
                        alignItems: isMobile ? 'flex-start' : 'center',
                        gap: isMobile ? 6 : 12,
                        width: '100%'
                      }}>
                        <span style={{ fontSize: isMobile ? 14 : 16, fontWeight: 500, flexShrink: 0 }}>
                          第{item.chapter_number}章：{item.title}
                        </span>
                        <Space wrap size={isMobile ? 4 : 8}>
                          <Tag color={getStatusColor(item.status)}>{getStatusText(item.status)}</Tag>
                          <Badge count={`${item.word_count || 0}字`} style={{ backgroundColor: token.colorSuccess }} />
                          {renderAnalysisStatus(item.id)}
                          {!canGenerateChapter(item) && (
                            <Tag icon={<LockOutlined />} color="warning" title={getGenerateDisabledReason(item)}>
                              需前置章节
                            </Tag>
                          )}
                        </Space>
                      </div>
                    }
                    description={
                      item.content ? (
                        <div style={{ marginTop: 8, color: token.colorTextSecondary, lineHeight: 1.6, fontSize: isMobile ? 12 : 14 }}>
                          {item.content.substring(0, isMobile ? 80 : 150)}
                          {item.content.length > (isMobile ? 80 : 150) && '...'}
                        </div>
                      ) : (
                        <span style={{ color: token.colorTextTertiary, fontSize: isMobile ? 12 : 14 }}>暂无内容</span>
                      )
                    }
                  />

                  {isMobile && (
                    <Space style={{ marginTop: 12, width: '100%', justifyContent: 'flex-end' }} wrap>
                      <Button
                        type="text"
                        icon={<ReadOutlined />}
                        onClick={() => handleOpenReader(item)}
                        size="small"
                        disabled={!item.content || item.content.trim() === ''}
                        title={!item.content || item.content.trim() === '' ? '暂无内容' : '阅读'}
                      />
                      <Button
                        type="text"
                        icon={<EditOutlined />}
                        onClick={() => handleOpenEditor(item.id)}
                        size="small"
                        title="编辑"
                      />
                      {(() => {
                        const task = analysisTasksMap[item.id];
                        const isAnalyzing = task && (task.status === 'pending' || task.status === 'running');
                        const hasContent = item.content && item.content.trim() !== '';

                        return (
                          <Button
                            type="text"
                            icon={isAnalyzing ? <SyncOutlined spin /> : <FundOutlined />}
                            onClick={() => handleShowAnalysis(item.id)}
                            size="small"
                            disabled={!hasContent || isAnalyzing}
                            loading={isAnalyzing}
                            title={
                              !hasContent ? '请先生成章节内容' :
                                isAnalyzing ? '分析中' :
                                  '分析'
                            }
                          />
                        );
                      })()}
                      <Button
                        type="text"
                        icon={<SettingOutlined />}
                        onClick={() => handleOpenModal(item.id)}
                        size="small"
                        title="修改"
                      />
                    </Space>
                  )}
                </div>
              </List.Item>
            )}
          />
        ) : (
          // one-to-many 模式：按大纲分组显示
          <Collapse
            bordered={false}
            defaultActiveKey={pagedGroupedChapters.length > 0 ? ['0'] : []}
            destroyInactivePanel
            expandIcon={({ isActive }) => <CaretRightOutlined rotate={isActive ? 90 : 0} />}
            style={{ background: 'transparent' }}
          >
            {pagedGroupedChapters.map((group, groupIndex) => (
              <Collapse.Panel
                key={groupIndex.toString()}
                header={
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <Tag color={group.outlineId ? 'blue' : 'default'} style={{ margin: 0 }}>
                      {group.outlineId ? `📖 大纲 ${group.outlineOrder}` : '📝 未分类'}
                    </Tag>
                    <span style={{ fontWeight: 600, fontSize: 16 }}>
                      {group.outlineTitle}
                    </span>
                    <Badge
                      count={`${group.chapters.length} 章`}
                      style={{ backgroundColor: token.colorSuccess }}
                    />
                    <Badge
                      count={`${group.chapters.reduce((sum, ch) => sum + (ch.word_count || 0), 0)} 字`}
                      style={{ backgroundColor: token.colorPrimary }}
                    />
                  </div>
                }
                style={{
                  marginBottom: 16,
                  background: token.colorBgContainer,
                  borderRadius: token.borderRadius,
                  border: `1px solid ${token.colorBorderSecondary}`,
                }}
              >
                <List
                  dataSource={group.chapters}
                  renderItem={(item) => (
                    <List.Item
                      id={`chapter-item-${item.id}`}
                      style={{
                        padding: '16px 0',
                        borderRadius: 8,
                        transition: 'background 0.3s ease',
                        flexDirection: isMobile ? 'column' : 'row',
                        alignItems: isMobile ? 'flex-start' : 'center',
                      }}
                      actions={isMobile ? undefined : [
                        <Button
                          type="text"
                          icon={<ReadOutlined />}
                          onClick={() => handleOpenReader(item)}
                          disabled={!item.content || item.content.trim() === ''}
                          title={!item.content || item.content.trim() === '' ? '暂无内容' : '沉浸式阅读'}
                        >
                          阅读
                        </Button>,
                        <Button
                          type="text"
                          icon={<EditOutlined />}
                          onClick={() => handleOpenEditor(item.id)}
                        >
                          编辑
                        </Button>,
                        (() => {
                          const task = analysisTasksMap[item.id];
                          const isAnalyzing = task && (task.status === 'pending' || task.status === 'running');
                          const hasContent = item.content && item.content.trim() !== '';

                          return (
                            <Button
                              type="text"
                              icon={isAnalyzing ? <SyncOutlined spin /> : <FundOutlined />}
                              onClick={() => handleShowAnalysis(item.id)}
                              disabled={!hasContent || isAnalyzing}
                              loading={isAnalyzing}
                              title={
                                !hasContent ? '请先生成章节内容' :
                                  isAnalyzing ? '分析进行中，请稍候...' :
                                    ''
                              }
                            >
                              {isAnalyzing ? '分析中' : '分析'}
                            </Button>
                          );
                        })(),
                        <Button
                          type="text"
                          icon={<SettingOutlined />}
                          onClick={() => handleOpenModal(item.id)}
                        >
                          修改
                        </Button>,
                        // 只在 one-to-many 模式下显示删除按钮
                        ...(currentProject.outline_mode === 'one-to-many' ? [
                          <Popconfirm
                            title="确定删除这个章节吗？"
                            description="删除后将无法恢复，章节内容和分析结果都将被删除。"
                            onConfirm={() => handleDeleteChapter(item.id)}
                            okText="确定删除"
                            cancelText="取消"
                            okButtonProps={{ danger: true }}
                          >
                            <Button
                              type="text"
                              danger
                              icon={<DeleteOutlined />}
                            >
                              删除
                            </Button>
                          </Popconfirm>
                        ] : []),
                      ]}
                    >
                      <div style={{ width: '100%' }}>
                        <List.Item.Meta
                          avatar={!isMobile && <FileTextOutlined style={{ fontSize: 32, color: token.colorPrimary }} />}
                          title={
                            <div style={{
                              display: 'flex',
                              flexDirection: isMobile ? 'column' : 'row',
                              alignItems: isMobile ? 'flex-start' : 'center',
                              gap: isMobile ? 6 : 12,
                              width: '100%'
                            }}>
                              <span style={{ fontSize: isMobile ? 14 : 16, fontWeight: 500, flexShrink: 0 }}>
                                第{item.chapter_number}章：{item.title}
                              </span>
                              <Space wrap size={isMobile ? 4 : 8}>
                                <Tag color={getStatusColor(item.status)}>{getStatusText(item.status)}</Tag>
                                <Badge count={`${item.word_count || 0}字`} style={{ backgroundColor: token.colorSuccess }} />
                                {renderAnalysisStatus(item.id)}
                                {!canGenerateChapter(item) && (
                                  <Tag icon={<LockOutlined />} color="warning" title={getGenerateDisabledReason(item)}>
                                    需前置章节
                                  </Tag>
                                )}
                                <Space size={4}>
                                  {item.expansion_plan && (
                                    <InfoCircleOutlined
                                      title="查看展开详情"
                                      style={{ color: token.colorPrimary, cursor: 'pointer', fontSize: 16 }}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        showExpansionPlanModal(item);
                                      }}
                                    />
                                  )}
                                  <FormOutlined
                                    title={item.expansion_plan ? "编辑规划信息" : "创建规划信息"}
                                    style={{ color: token.colorSuccess, cursor: 'pointer', fontSize: 16 }}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleOpenPlanEditor(item);
                                    }}
                                  />
                                </Space>
                              </Space>
                            </div>
                          }
                          description={
                            item.content ? (
                              <div style={{ marginTop: 8, color: token.colorTextSecondary, lineHeight: 1.6, fontSize: isMobile ? 12 : 14 }}>
                                {item.content.substring(0, isMobile ? 80 : 150)}
                                {item.content.length > (isMobile ? 80 : 150) && '...'}
                              </div>
                            ) : (
                              <span style={{ color: token.colorTextTertiary, fontSize: isMobile ? 12 : 14 }}>暂无内容</span>
                            )
                          }
                        />

                        {isMobile && (
                          <Space style={{ marginTop: 12, width: '100%', justifyContent: 'flex-end' }} wrap>
                            <Button
                              type="text"
                              icon={<ReadOutlined />}
                              onClick={() => handleOpenReader(item)}
                              size="small"
                              disabled={!item.content || item.content.trim() === ''}
                              title={!item.content || item.content.trim() === '' ? '暂无内容' : '阅读'}
                            />
                            <Button
                              type="text"
                              icon={<EditOutlined />}
                              onClick={() => handleOpenEditor(item.id)}
                              size="small"
                              title="编辑"
                            />
                            {(() => {
                              const task = analysisTasksMap[item.id];
                              const isAnalyzing = task && (task.status === 'pending' || task.status === 'running');
                              const hasContent = item.content && item.content.trim() !== '';

                              return (
                                <Button
                                  type="text"
                                  icon={isAnalyzing ? <SyncOutlined spin /> : <FundOutlined />}
                                  onClick={() => handleShowAnalysis(item.id)}
                                  size="small"
                                  disabled={!hasContent || isAnalyzing}
                                  loading={isAnalyzing}
                                  title={
                                    !hasContent ? '请先生成章节内容' :
                                      isAnalyzing ? '分析中' :
                                        '分析'
                                  }
                                />
                              );
                            })()}
                            <Button
                              type="text"
                              icon={<SettingOutlined />}
                              onClick={() => handleOpenModal(item.id)}
                              size="small"
                              title="修改"
                            />
                            {/* 只在 one-to-many 模式下显示删除按钮 */}
                            {currentProject.outline_mode === 'one-to-many' && (
                              <Popconfirm
                                title="确定删除？"
                                description="删除后无法恢复"
                                onConfirm={() => handleDeleteChapter(item.id)}
                                okText="删除"
                                cancelText="取消"
                                okButtonProps={{ danger: true }}
                              >
                                <Button
                                  type="text"
                                  danger
                                  icon={<DeleteOutlined />}
                                  size="small"
                                  title="删除章节"
                                />
                              </Popconfirm>
                            )}
                          </Space>
                        )}
                      </div>
                    </List.Item>
                  )}
                />
              </Collapse.Panel>
            ))}
          </Collapse>
        )}
      </div>

      {filteredSortedChapters.length > 0 && (
        <div style={{ paddingTop: 12, display: 'flex', justifyContent: 'flex-end' }}>
          <Pagination
            current={chapterPage}
            pageSize={chapterPageSize}
            total={filteredSortedChapters.length}
            showSizeChanger
            pageSizeOptions={['10', '20', '50', '100']}
            onChange={(page, size) => {
              setChapterPage(page);
              if (size !== chapterPageSize) {
                setChapterPageSize(size);
                setChapterPage(1);
              }
            }}
            showTotal={(total) => `共 ${total} 条`}
            size={isMobile ? 'small' : 'default'}
          />
        </div>
      )}

      <Modal
        title="导入章节"
        open={importModalVisible}
        onCancel={() => {
          setImportModalVisible(false);
          setImportFileList([]);
        }}
        onOk={handleImportSubmit}
        confirmLoading={importing}
        okText="开始导入"
        cancelText="取消"
        centered
        width={isMobile ? 'calc(100vw - 32px)' : 680}
      >
        <Form
          form={importForm}
          layout="vertical"
          initialValues={{
            import_mode: 'auto_split',
            import_position: 'append',
            conflict_strategy: 'skip',
            status: 'draft',
          }}
        >
          <Form.Item label="导入文件" required>
            <Dragger
              multiple
              accept=".txt,.md,.markdown,text/plain,text/markdown"
              fileList={importFileList}
              beforeUpload={() => false}
              onChange={({ fileList }) => setImportFileList(fileList)}
              onRemove={(file) => {
                setImportFileList(prev => prev.filter(item => item.uid !== file.uid));
              }}
            >
              <p className="ant-upload-drag-icon">
                <UploadOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽 TXT / Markdown 文件到这里</p>
              <p className="ant-upload-hint">单文件可智能拆分多章；多文件可按文件逐章导入。</p>
            </Dragger>
          </Form.Item>

          <Form.Item label="导入方式" name="import_mode">
            <Radio.Group
              optionType="button"
              buttonStyle="solid"
              onChange={(event) => setImportMode(event.target.value)}
              options={[
                { value: 'auto_split', label: '智能拆分章节' },
                { value: 'file_as_chapter', label: '每个文件一章' },
              ]}
            />
          </Form.Item>

          {importMode === 'auto_split' && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message="会复用拆书导入的章节识别规则，适合整卷 TXT 或一个文件内包含多章的文本。"
            />
          )}

          {importMode === 'file_as_chapter' && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message="每个文件会作为独立章节导入，优先使用文件首行或文件名作为章节标题。"
            />
          )}

          <Form.Item label="导入位置" name="import_position">
            <Radio.Group
              optionType="button"
              buttonStyle="solid"
              onChange={(event) => setImportPosition(event.target.value)}
              options={[
                { value: 'append', label: '追加到末尾' },
                { value: 'custom', label: '指定起始章' },
              ]}
            />
          </Form.Item>

          {importPosition === 'custom' && (
            <Space size={12} align="start" style={{ width: '100%' }}>
              <Form.Item
                label="起始章节"
                name="start_chapter_number"
                rules={[{ required: true, message: '请输入起始章节号' }]}
              >
                <InputNumber min={1} precision={0} style={{ width: 160 }} addonBefore="第" addonAfter="章" />
              </Form.Item>
              <Form.Item label="遇到同序号章节" name="conflict_strategy">
                <Select style={{ width: 160 }}>
                  <Select.Option value="skip">跳过导入</Select.Option>
                  <Select.Option value="overwrite">覆盖旧章</Select.Option>
                </Select>
              </Form.Item>
            </Space>
          )}

          <Form.Item label="导入后状态" name="status">
            <Select>
              <Select.Option value="draft">草稿</Select.Option>
              <Select.Option value="pending">待处理</Select.Option>
              <Select.Option value="writing">创作中</Select.Option>
              <Select.Option value="completed">已完成</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="导出项目章节"
        open={exportModalVisible}
        onCancel={() => setExportModalVisible(false)}
        onOk={handleExportSubmit}
        confirmLoading={exporting}
        okText="开始导出"
        cancelText="取消"
        centered
        width={isMobile ? 'calc(100vw - 32px)' : 560}
      >
        <Form
          form={exportForm}
          layout="vertical"
          initialValues={{ rangeType: 'all', exportMode: 'merged' }}
        >
          <Form.Item label="导出范围" name="rangeType">
            <Radio.Group
              optionType="button"
              buttonStyle="solid"
              onChange={(event) => setExportRangeType(event.target.value)}
              options={[
                { value: 'all', label: '全部章节' },
                { value: 'custom', label: '指定范围' },
              ]}
            />
          </Form.Item>

          {exportRangeType === 'custom' && (
            <Space size={12} style={{ width: '100%' }} align="start">
              <Form.Item
                label="起始章节"
                name="start_chapter"
                rules={[{ required: true, message: '请输入起始章节' }]}
              >
                <InputNumber min={1} precision={0} style={{ width: 160 }} addonBefore="第" addonAfter="章" />
              </Form.Item>
              <Form.Item
                label="结束章节"
                name="end_chapter"
                rules={[{ required: true, message: '请输入结束章节' }]}
              >
                <InputNumber min={1} precision={0} style={{ width: 160 }} addonBefore="第" addonAfter="章" />
              </Form.Item>
            </Space>
          )}

          <Form.Item label="导出方式" name="exportMode">
            <Radio.Group
              optionType="button"
              buttonStyle="solid"
              options={[
                { value: 'merged', label: '合并TXT' },
                { value: 'split', label: '分章ZIP' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editingId ? '编辑章节信息' : '添加章节'}
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        footer={null}
        centered
        width={isMobile ? 'calc(100vw - 32px)' : 520}
        style={isMobile ? {
          maxWidth: 'calc(100vw - 32px)',
          margin: '0 auto',
          padding: '0 16px'
        } : undefined}
        styles={{
          body: {
            maxHeight: isMobile ? 'calc(100vh - 200px)' : 'calc(80vh - 110px)',
            overflowY: 'auto'
          }
        }}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            label="章节标题"
            name="title"
            tooltip={
              currentProject.outline_mode === 'one-to-one'
                ? "章节标题由大纲管理，请在大纲页面修改"
                : "一对多模式下可以修改章节标题"
            }
            rules={
              currentProject.outline_mode === 'one-to-many'
                ? [{ required: true, message: '请输入章节标题' }]
                : undefined
            }
          >
            <Input
              placeholder="输入章节标题"
              disabled={currentProject.outline_mode === 'one-to-one'}
            />
          </Form.Item>

          <Form.Item
            label="章节序号"
            name="chapter_number"
            tooltip="章节序号不允许修改，请删除对应大纲，重新生成"
          >
            <Input type="number" placeholder="章节排序序号" disabled />
          </Form.Item>

          <Form.Item label="状态" name="status">
            <Select placeholder="选择状态">
              <Select.Option value="draft">草稿</Select.Option>
              <Select.Option value="pending">待处理</Select.Option>
              <Select.Option value="writing">创作中</Select.Option>
              <Select.Option value="completed">已完成</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item>
            <Space style={{ float: 'right' }}>
              <Button onClick={() => setIsModalOpen(false)}>取消</Button>
              <Button type="primary" htmlType="submit">
                更新
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑章节内容"
        open={isEditorOpen}
        onCancel={() => {
          if (isGenerating) {
            message.warning('AI正在创作中，请等待完成后再关闭');
            return;
          }
          setIsEditorOpen(false);
        }}
        closable={!isGenerating}
        maskClosable={false}
        keyboard={!isGenerating}
        width={isMobile ? 'calc(100vw - 32px)' : '85%'}
        centered
        style={isMobile ? {
          maxWidth: 'calc(100vw - 32px)',
          margin: '0 auto',
          padding: '0 16px'
        } : undefined}
        styles={{
          body: {
            maxHeight: isMobile ? 'calc(100vh - 200px)' : 'calc(100vh - 110px)',
            overflowY: 'auto',
            padding: isMobile ? '16px 12px' : '8px'
          }
        }}
        footer={null}
      >
        <Form form={editorForm} layout="vertical" onFinish={handleEditorSubmit}>
          {/* 章节标题和AI创作按钮 */}
          <Form.Item
            label="章节标题"
            tooltip="（1-1模式请在大纲修改，1-N模式请使用修改按钮编辑）"
            style={{ marginBottom: isMobile ? 16 : 12 }}
          >
            <Space.Compact style={{ width: '100%' }}>
              <Form.Item name="title" noStyle>
                <Input disabled style={{ flex: 1 }} />
              </Form.Item>
              <Button
                icon={<ThunderboltOutlined />}
                onClick={() => openChapterAiTool(editorForm, 'title', '章节标题', 'generate_title')}
                disabled={isGenerating}
                title="根据摘要、正文和关联大纲生成标题"
              >
                {isMobile ? '标题' : 'AI标题'}
              </Button>
              <Button
                icon={<HighlightOutlined />}
                onClick={() => openChapterAiTool(editorForm, 'title', '章节标题', 'polish')}
                disabled={isGenerating}
                title="润色当前章节标题"
              >
                润色
              </Button>
              {editingId && (() => {
                const currentChapter = chapters.find(c => c.id === editingId);
                const canGenerate = currentChapter ? canGenerateChapter(currentChapter) : false;
                const disabledReason = currentChapter ? getGenerateDisabledReason(currentChapter) : '';

                return (
                  <>
                  <Button
                    type="primary"
                    icon={canGenerate ? <ThunderboltOutlined /> : <LockOutlined />}
                    onClick={() => currentChapter && showGenerateModal(currentChapter)}
                    loading={isContinuing}
                    disabled={!canGenerate}
                    danger={!canGenerate}
                    style={{ fontWeight: 'bold' }}
                    title={!canGenerate ? disabledReason : '根据大纲和前置章节内容创作（流式）'}
                  >
                    {isMobile ? 'AI' : 'AI创作'}
                  </Button>
                  <Button
                    icon={<RocketOutlined />}
                    onClick={handleBackgroundGenerate}
                    disabled={!canGenerate || isContinuing}
                    style={{ fontWeight: 'bold' }}
                    title={!canGenerate ? disabledReason : '后台生成：关闭浏览器也不影响，完成后自动保存'}
                  >
                    {isMobile ? '后台' : '后台生成'}
                  </Button>
                  </>
                );
              })()}
            </Space.Compact>
          </Form.Item>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <span style={{ color: token.colorTextSecondary }}>章节摘要（可选）</span>
            <Space wrap size={8}>
              <Button
                size="small"
                icon={<ThunderboltOutlined />}
                onClick={() => openChapterAiTool(editorForm, 'summary', '章节摘要', 'generate_summary')}
                disabled={isGenerating}
              >
                AI生成
              </Button>
              <Button
                size="small"
                icon={<HighlightOutlined />}
                onClick={() => openChapterAiTool(editorForm, 'summary', '章节摘要', 'polish')}
                disabled={isGenerating}
              >
                润色
              </Button>
            </Space>
          </div>

          <Form.Item name="summary" style={{ marginBottom: isMobile ? 16 : 12 }}>
            <TextArea
              rows={3}
              placeholder="简要描述本章内容，可用于后续分析和衔接..."
              disabled={isGenerating}
            />
          </Form.Item>


          {/* 第一行：写作风格 + 叙事角度 */}
          <div style={{
            display: isMobile ? 'block' : 'flex',
            gap: isMobile ? 0 : 16,
            marginBottom: isMobile ? 0 : 12
          }}>
            <Form.Item
              label="写作风格"
              tooltip="选择AI创作时使用的写作风格"
              required
              style={{ flex: 1, marginBottom: isMobile ? 16 : 0 }}
            >
              <Select
                placeholder="请选择写作风格"
                value={selectedStyleId}
                onChange={setSelectedStyleId}
                disabled={isGenerating}
                status={!selectedStyleId ? 'error' : undefined}
              >
                {writingStyles.map(style => (
                  <Select.Option key={style.id} value={style.id}>
                    {style.name}{style.is_default && ' (默认)'}
                  </Select.Option>
                ))}
              </Select>
              {!selectedStyleId && (
                <div style={{ color: token.colorError, fontSize: 12, marginTop: 4 }}>请选择写作风格</div>
              )}
            </Form.Item>

            <Form.Item
              label="叙事角度"
              tooltip="第一人称(我)代入感强；第三人称(他/她)更客观；全知视角洞悉一切"
              style={{ flex: 1, marginBottom: isMobile ? 16 : 0 }}
            >
              <Select
                placeholder={`项目默认: ${getNarrativePerspectiveText(currentProject?.narrative_perspective)}`}
                value={temporaryNarrativePerspective}
                onChange={setTemporaryNarrativePerspective}
                allowClear
                disabled={isGenerating}
              >
                <Select.Option value="第一人称">第一人称(我)</Select.Option>
                <Select.Option value="第三人称">第三人称(他/她)</Select.Option>
                <Select.Option value="全知视角">全知视角</Select.Option>
              </Select>
              {temporaryNarrativePerspective && (
                <div style={{ color: token.colorSuccess, fontSize: 12, marginTop: 4 }}>
                  ✓ {getNarrativePerspectiveText(temporaryNarrativePerspective)}
                </div>
              )}
            </Form.Item>
          </div>

          {/* 第二行：目标字数 + AI模型 */}
          <div style={{
            display: isMobile ? 'block' : 'flex',
            gap: isMobile ? 0 : 16,
            marginBottom: isMobile ? 16 : 12
          }}>
            <Form.Item
              label="目标字数"
              tooltip="AI生成章节时的目标字数，实际可能略有偏差（修改后会自动记住）"
              style={{ flex: 1, marginBottom: isMobile ? 16 : 0 }}
            >
              <InputNumber
                min={500}
                max={10000}
                step={100}
                value={targetWordCount}
                onChange={(value) => {
                  const newValue = value || DEFAULT_WORD_COUNT;
                  setTargetWordCount(newValue);
                  setCachedWordCount(newValue);
                }}
                disabled={isGenerating}
                style={{ width: '100%' }}
                formatter={(value) => `${value} 字`}
                parser={(value) => parseInt(value?.replace(' 字', '') || '0', 10) as unknown as 500}
              />
            </Form.Item>

            <Form.Item
              label="AI模型"
              tooltip="选择用于生成章节内容的AI模型，不选择则使用默认模型"
              style={{ flex: 1, marginBottom: isMobile ? 16 : 0 }}
            >
              <Select
                placeholder={selectedModel ? `默认: ${availableModels.find(m => m.value === selectedModel)?.label || selectedModel}` : "使用默认模型"}
                value={selectedModel}
                onChange={setSelectedModel}
                allowClear
                disabled={isGenerating}
                showSearch
                optionFilterProp="label"
              >
                {availableModels.map(model => (
                  <Select.Option key={model.value} value={model.value} label={model.label}>
                    {model.label}
                  </Select.Option>
                ))}
              </Select>
            </Form.Item>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <span style={{ color: token.colorTextSecondary }}>章节内容</span>
            <Space wrap size={8}>
              <Button
                size="small"
                icon={<HighlightOutlined />}
                onClick={() => openChapterAiTool(editorForm, 'content', '章节正文', 'polish')}
                disabled={isGenerating}
              >
                润色全文
              </Button>
              <Button
                size="small"
                icon={<ThunderboltOutlined />}
                onClick={handleOpenFullChapterRegenerate}
                disabled={isGenerating}
              >
                提示词重写整章
              </Button>
              <Button
                size="small"
                icon={<EditOutlined />}
                onClick={handleOpenSelectedTextRegenerate}
                disabled={isGenerating}
              >
                精准重写选中段落
              </Button>
            </Space>
          </div>

          <Form.Item name="content">
            <TextArea
              ref={contentTextAreaRef}
              rows={isMobile ? 12 : 20}
              placeholder="开始写作..."
              style={{ fontFamily: 'monospace', fontSize: isMobile ? 12 : 14 }}
              disabled={isGenerating}
              onSelect={handleTextSelection}
            />
          </Form.Item>

          {/* 局部重写浮动工具栏 */}
          <div data-partial-regenerate-toolbar>
            <PartialRegenerateToolbar
              visible={partialRegenerateToolbarVisible && !isGenerating}
              position={partialRegenerateToolbarPosition}
              selectedText={selectedTextForRegenerate}
              onRegenerate={handleOpenPartialRegenerate}
            />
          </div>

          <Form.Item>
            <Space style={{ width: '100%', justifyContent: 'flex-end', flexDirection: isMobile ? 'column' : 'row', alignItems: isMobile ? 'stretch' : 'center' }}>
              <Space style={{ width: isMobile ? '100%' : 'auto' }}>
                <Button
                  onClick={() => {
                    if (isGenerating) {
                      message.warning('AI正在创作中，请等待完成后再关闭');
                      return;
                    }
                    setIsEditorOpen(false);
                  }}
                  block={isMobile}
                  disabled={isGenerating}
                >
                  取消
                </Button>
                <Button
                  type="primary"
                  htmlType="submit"
                  block={isMobile}
                  disabled={isGenerating}
                >
                  保存章节
                </Button>
              </Space>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {analysisChapterId && (
        <ChapterAnalysis
          chapterId={analysisChapterId}
          visible={analysisVisible}
          onClose={() => {
            setAnalysisVisible(false);

            // 刷新章节列表以显示最新内容
            refreshChapters();

            // 刷新项目信息以更新字数统计
            if (currentProject) {
              projectApi.getProject(currentProject.id)
                .then(updatedProject => {
                  setCurrentProject(updatedProject);
                })
                .catch(error => {
                  console.error('刷新项目信息失败:', error);
                });
            }

            // 延迟500ms后批量刷新分析状态，避免单章接口高频调用
            setTimeout(() => {
              loadAnalysisTasks();
            }, 500);

            setAnalysisChapterId(null);
          }}
        />
      )}

      {/* 批量生成对话框 */}
      <Modal
        title={
          <Space>
            <RocketOutlined style={{ color: token.colorInfo }} />
            <span>批量生成章节内容</span>
          </Space>
        }
        open={batchGenerateVisible}
        onCancel={() => {
          if (batchGenerating) {
            modal.confirm({
              title: '确认取消',
              content: '批量生成正在进行中，确定要取消吗？',
              okText: '确定取消',
              cancelText: '继续生成',
              centered: true,
              onOk: () => {
                handleCancelBatchGenerate();
                setBatchGenerateVisible(false);
              },
            });
          } else {
            setBatchGenerateVisible(false);
          }
        }}
        footer={!batchGenerating ? (
          <Space style={{ width: '100%', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            <Button onClick={() => setBatchGenerateVisible(false)}>
              取消
            </Button>
            <Button type="primary" icon={<RocketOutlined />} onClick={() => batchForm.submit()}>
              开始批量生成
            </Button>
          </Space>
        ) : null}
        width={isMobile ? 'calc(100vw - 32px)' : 700}
        centered
        closable={!batchGenerating}
        maskClosable={!batchGenerating}
        style={isMobile ? {
          maxWidth: 'calc(100vw - 32px)',
          margin: '0 auto',
          padding: '0 16px'
        } : undefined}
        styles={{
          body: {
            maxHeight: isMobile ? 'calc(100vh - 200px)' : 'calc(100vh - 260px)',
            overflowY: 'auto',
            overflowX: 'hidden'
          }
        }}
      >
        {!batchGenerating ? (
          <Form
            form={batchForm}
            layout="vertical"
            onFinish={handleBatchGenerate}
            initialValues={{
              startChapterNumber: sortedChapters.find(ch => !ch.content || ch.content.trim() === '')?.chapter_number || 1,
              count: 5,
              enableAnalysis: true,
              styleId: selectedStyleId,
              targetWordCount: getCachedWordCount(),
              model: selectedModel,
            }}
          >
            <Alert
              message="批量生成说明：严格按序生成 | 统一风格字数 | 任一失败则终止"
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />

            {/* 第一行：起始章节 + 生成数量 */}
            <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? 0 : 16 }}>
              <Form.Item
                label="起始章节"
                name="startChapterNumber"
                rules={[{ required: true, message: '请选择' }]}
                style={{ flex: 1, marginBottom: 12 }}
              >
                <Select placeholder="选择起始章节">
                  {sortedChapters
                    .filter(ch => !ch.content || ch.content.trim() === '')
                    .filter(ch => canGenerateChapter(ch))
                    .map(ch => (
                      <Select.Option key={ch.id} value={ch.chapter_number}>
                        第{ch.chapter_number}章：{ch.title}
                      </Select.Option>
                    ))}
                </Select>
              </Form.Item>

              <Form.Item
                label="生成数量"
                name="count"
                rules={[{ required: true, message: '请选择' }]}
                style={{ marginBottom: 12 }}
              >
                <Radio.Group buttonStyle="solid" size={isMobile ? 'small' : 'middle'}>
                  <Radio.Button value={5}>5章</Radio.Button>
                  <Radio.Button value={10}>10章</Radio.Button>
                  <Radio.Button value={15}>15章</Radio.Button>
                  <Radio.Button value={20}>20章</Radio.Button>
                </Radio.Group>
              </Form.Item>
            </div>

            {/* 第二行：写作风格 + 目标字数 */}
            <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? 0 : 16 }}>
              <Form.Item
                label="写作风格"
                name="styleId"
                rules={[{ required: true, message: '请选择' }]}
                style={{ flex: 1, marginBottom: 12 }}
              >
                <Select placeholder="请选择写作风格" showSearch optionFilterProp="children">
                  {writingStyles.map(style => (
                    <Select.Option key={style.id} value={style.id}>
                      {style.name}{style.is_default && ' (默认)'}
                    </Select.Option>
                  ))}
                </Select>
              </Form.Item>

              <Form.Item
                label="目标字数"
                name="targetWordCount"
                rules={[{ required: true, message: '请设置' }]}
                tooltip="修改后自动记住"
                style={{ flex: 1, marginBottom: 12 }}
              >
                <InputNumber
                  min={500}
                  max={10000}
                  step={100}
                  style={{ width: '100%' }}
                  formatter={(value) => `${value} 字`}
                  parser={(value) => parseInt(value?.replace(' 字', '') || '0', 10) as unknown as 500}
                  onChange={(value) => {
                    if (value) {
                      setCachedWordCount(value);
                    }
                  }}
                />
              </Form.Item>
            </div>

            {/* 第三行：AI模型 + 同步分析 */}
            <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? 0 : 16 }}>
              <Form.Item
                label="AI模型"
                tooltip="不选则使用默认模型"
                style={{ flex: 1, marginBottom: 12 }}
              >
                <Select
                  placeholder={batchSelectedModel ? `默认: ${availableModels.find(m => m.value === batchSelectedModel)?.label || batchSelectedModel}` : "使用默认模型"}
                  value={batchSelectedModel}
                  onChange={setBatchSelectedModel}
                  allowClear
                  showSearch
                  optionFilterProp="label"
                >
                  {availableModels.map(model => (
                    <Select.Option key={model.value} value={model.value} label={model.label}>
                      {model.label}
                    </Select.Option>
                  ))}
                </Select>
              </Form.Item>

              <Form.Item
                label="同步分析"
                name="enableAnalysis"
                tooltip="必须开启，确保剧情连贯"
                style={{ marginBottom: 12 }}
              >
                <Radio.Group disabled>
                  <Radio value={true}>
                    <span style={{ fontSize: 12, color: token.colorSuccess }}>✓ 自动更新角色状态</span>
                  </Radio>
                </Radio.Group>
              </Form.Item>
            </div>
          </Form>
        ) : (
          <div>
            <Alert
              message="温馨提示"
              description={
                <ul style={{ margin: '8px 0 0 0', paddingLeft: 20 }}>
                  <li>批量生成需要一定时间，可以切换到其他页面</li>
                  <li>关闭页面后重新打开，会自动恢复任务进度</li>
                  <li>可以随时点击"取消任务"按钮中止生成</li>
                  {batchProgress?.estimated_time_minutes && batchProgress.completed === 0 && (
                    <li>⏱️ 预计耗时：约 {batchProgress.estimated_time_minutes} 分钟</li>
                  )}
                </ul>
              }
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />

            <div style={{ textAlign: 'center' }}>
              <Button
                danger
                icon={<StopOutlined />}
                onClick={() => {
                  modal.confirm({
                    title: '确认取消',
                    content: '确定要取消批量生成吗？已生成的章节将保留。',
                    okText: '确定取消',
                    cancelText: '继续生成',
                    okButtonProps: { danger: true },
                    onOk: handleCancelBatchGenerate,
                  });
                }}
              >
                取消任务
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* 单章节生成进度显示 */}
      <SSELoadingOverlay
        loading={isGenerating}
        progress={singleChapterProgress}
        message={singleChapterProgressMessage}
      />

      {/* 章节阅读器 */}
      {readingChapter && (
        <ChapterReader
          visible={readerVisible}
          chapter={readingChapter}
          onClose={() => {
            setReaderVisible(false);
            setReadingChapter(null);
          }}
          onChapterChange={handleReaderChapterChange}
        />
      )}

      {/* 局部重写弹窗 */}
      {editingId && (
        <PartialRegenerateModal
          visible={partialRegenerateModalVisible}
          chapterId={editingId}
          title={partialRegenerateTitle}
          selectedText={selectedTextForRegenerate}
          startPosition={selectionStartPosition}
          endPosition={selectionEndPosition}
          styleId={selectedStyleId}
          onClose={() => setPartialRegenerateModalVisible(false)}
          onApply={handleApplyPartialRegenerate}
        />
      )}

      {/* 规划编辑器 */}
      {editingPlanChapter && currentProject && (() => {
        let parsedPlanData = null;
        try {
          if (editingPlanChapter.expansion_plan) {
            parsedPlanData = JSON.parse(editingPlanChapter.expansion_plan);
          }
        } catch (error) {
          console.error('解析规划数据失败:', error);
        }

        return (
          <ExpansionPlanEditor
            visible={planEditorVisible}
            planData={parsedPlanData}
            chapterSummary={editingPlanChapter.summary || null}
            projectId={currentProject.id}
            onSave={handleSavePlan}
            onCancel={() => {
              setPlanEditorVisible(false);
              setEditingPlanChapter(null);
            }}
          />
        );
      })()}
    </div>
  );
}
