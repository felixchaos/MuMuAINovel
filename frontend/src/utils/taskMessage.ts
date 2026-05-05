import { message } from 'antd';

type TaskMessageOptions = {
  detail?: string | null;
  duration?: number;
  key?: string;
  location?: 'backgroundPanel' | 'currentPage';
  cancellable?: boolean;
};

const DEFAULT_DURATION = 3;

const getLocationText = (options?: Pick<TaskMessageOptions, 'location' | 'cancellable'>) => {
  if (options?.location === 'currentPage') {
    return '可在当前页面查看进度';
  }

  return options?.cancellable
    ? '可在右下角后台任务面板查看进度或取消'
    : '可在右下角后台任务面板查看进度';
};

const appendDetail = (text: string, detail?: string | null) => (
  detail ? `${text}，${detail}` : text
);

const show = (
  type: 'info' | 'success' | 'warning' | 'error',
  content: string,
  options?: Pick<TaskMessageOptions, 'duration' | 'key'>,
) => {
  const duration = options?.duration ?? DEFAULT_DURATION;
  if (options?.key) {
    message[type]({ key: options.key, content, duration });
    return;
  }

  message[type](content, duration);
};

export const taskMessage = {
  started(taskName: string, options?: TaskMessageOptions) {
    const content = `${appendDetail(`${taskName}已开始`, options?.detail)}，${getLocationText(options)}`;
    show('info', content, options);
  },

  restored(taskName: string, options?: TaskMessageOptions) {
    const content = `检测到未完成的${taskName}，${getLocationText(options)}`;
    show('info', content, options);
  },

  completed(taskName: string, detail?: string | null, options?: Pick<TaskMessageOptions, 'duration' | 'key'>) {
    const content = detail ? `${taskName}已完成：${detail}` : `${taskName}已完成`;
    show('success', content, options);
  },

  failed(taskName: string, error?: string | null, options?: Pick<TaskMessageOptions, 'duration' | 'key'>) {
    show('error', `${taskName}失败：${error || '未知错误'}`, options);
  },

  cancelled(taskName: string, options?: Pick<TaskMessageOptions, 'duration' | 'key'>) {
    show('warning', `${taskName}已取消`, options);
  },
};
