/* eslint-disable @typescript-eslint/no-explicit-any */
export interface SSEMessage {
  type: 'progress' | 'chunk' | 'result' | 'error' | 'done';
  message?: string;
  progress?: number;
  word_count?: number;
  status?: 'processing' | 'success' | 'error' | 'warning';
  content?: string;
  data?: any;
  error?: string;
  code?: number;
}

export interface SSEClientOptions {
  onProgress?: (message: string, progress: number, status: string, wordCount?: number) => void;
  onChunk?: (content: string) => void;
  onResult?: (data: any) => void;
  onError?: (error: string, code?: number) => void;
  onComplete?: () => void;
  onConnectionError?: (error: Event) => void;
  signal?: AbortSignal;
}

export class SSEClient {
  private eventSource: EventSource | null = null;
  private url: string;
  private options: SSEClientOptions;
  private accumulatedContent: string = '';

  constructor(url: string, options: SSEClientOptions = {}) {
    this.url = url;
    this.options = options;
  }

  connect(): Promise<any> {
    return new Promise((resolve, reject) => {
      try {
        this.eventSource = new EventSource(this.url);

        this.eventSource.onmessage = (event) => {
          try {
            const message: SSEMessage = JSON.parse(event.data);
            this.handleMessage(message, resolve, reject);
          } catch (error) {
            console.error('解析SSE消息失败:', error);
          }
        };

        this.eventSource.onerror = (error) => {
          console.error('SSE连接错误:', error);
          if (this.options.onConnectionError) {
            this.options.onConnectionError(error);
          }
          this.close();
          reject(new Error('SSE连接失败'));
        };

      } catch (error) {
        reject(error);
      }
    });
  }

  private handleMessage(message: SSEMessage, resolve: (value: any) => void, reject: (reason?: any) => void) {
    switch (message.type) {
      case 'progress':
        if (this.options.onProgress && message.progress !== undefined) {
          this.options.onProgress(
            message.message || '',
            message.progress,
            message.status || 'processing',
            message.word_count
          );
        }
        break;

      case 'chunk':
        if (message.content) {
          this.accumulatedContent += message.content;
          if (this.options.onChunk) {
            this.options.onChunk(message.content);
          }
        }
        break;

      case 'result':
        if (this.options.onResult && message.data) {
          this.options.onResult(message.data);
        }
        break;

      case 'error':
        if (this.options.onError) {
          this.options.onError(message.error || '未知错误', message.code);
        }
        this.close();
        reject(new Error(message.error || '未知错误'));
        break;

      case 'done':
        if (this.options.onComplete) {
          this.options.onComplete();
        }
        this.close();
        if (!this.options.onResult && this.accumulatedContent) {
          resolve({ content: this.accumulatedContent });
        } else {
          resolve(true);
        }
        break;
    }
  }

  close() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  getAccumulatedContent(): string {
    return this.accumulatedContent;
  }
}

export class SSEPostClient {
  private url: string;
  private data: any;
  private options: SSEClientOptions;
  private abortController: AbortController | null = null;
  private accumulatedContent: string = '';
  private resultData: any = null;
  private settled = false;

  constructor(url: string, data: any, options: SSEClientOptions = {}) {
    this.url = url;
    this.data = data;
    this.options = options;
  }

  async connect(): Promise<any> {
    return new Promise((resolve, reject) => {
      this.connectInternal(resolve, reject);
    });
  }

  private async connectInternal(resolve: (value: any) => void, reject: (reason?: any) => void) {
      let externalSignal: AbortSignal | undefined;
      let abortFromExternalSignal: (() => void) | undefined;
      try {
        this.abortController = new AbortController();
        externalSignal = this.options.signal;
        abortFromExternalSignal = () => this.abort();

        if (externalSignal?.aborted) {
          this.abortController.abort();
        } else {
          externalSignal?.addEventListener('abort', abortFromExternalSignal, { once: true });
        }

        const response = await fetch(this.url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          credentials: 'include',
          body: JSON.stringify(this.data),
          signal: this.abortController.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();

        if (!reader) {
          throw new Error('无法获取响应流');
        }

        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();

          if (done) {
            break;
          }

          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split('\n\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.trim() === '' || line.startsWith(':')) {
              continue;
            }

            try {
              const dataLines = line
                .split('\n')
                .filter((item) => item.startsWith('data:'))
                .map((item) => item.replace(/^data:\s?/, ''));
              const rawData = dataLines.join('\n');
              if (rawData) {
                const data = JSON.parse(rawData);

                // 标准消息处理
                const message: SSEMessage = data;
                const shouldStop = await this.handleMessage(message, resolve, reject);
                if (shouldStop) {
                  return;
                }
              }
            } catch (error) {
              console.error('解析SSE消息失败:', error, line);
            }
          }
        }

      } catch (error: any) {
        if (this.settled) {
          return;
        }
        if (error.name === 'AbortError') {
          console.log('请求已取消');
          this.settled = true;
          reject(error);
        } else {
          console.error('SSE POST请求失败:', error);
          if (this.options.onError) {
            this.options.onError(error.message || '请求失败');
          }
          this.settled = true;
          reject(error);
        }
      } finally {
        if (externalSignal && abortFromExternalSignal) {
          externalSignal.removeEventListener('abort', abortFromExternalSignal);
        }
      }
  }

  private async handleMessage(
    message: SSEMessage,
    resolve: (value: any) => void,
    reject: (reason?: any) => void
  ): Promise<boolean> {
    if (this.settled) {
      return true;
    }

    switch (message.type) {
      case 'progress':
        if (this.options.onProgress && message.progress !== undefined) {
          this.options.onProgress(
            message.message || '',
            message.progress,
            message.status || 'processing',
            message.word_count
          );
        }
        return false;

      case 'chunk':
        if (message.content) {
          this.accumulatedContent += message.content;
          if (this.options.onChunk) {
            this.options.onChunk(message.content);
          }
        }
        return false;

      case 'result':
        if (this.options.onResult && message.data) {
          this.options.onResult(message.data);
        }
        this.resultData = message.data;
        return false;

      case 'error':
        if (this.options.onError) {
          this.options.onError(message.error || '未知错误', message.code);
        }
        this.settled = true;
        this.abort();
        reject(new Error(message.error || '未知错误'));
        return true;

      case 'done':
        if (this.options.onComplete) {
          this.options.onComplete();
        }
        this.settled = true;
        if (this.resultData) {
          resolve(this.resultData);
        } else if (this.accumulatedContent) {
          resolve({ content: this.accumulatedContent });
        } else {
          resolve(true);
        }
        return true;

      default:
        return false;
    }
  }

  abort() {
    if (this.abortController) {
      this.abortController.abort();
    }
  }

  getAccumulatedContent(): string {
    return this.accumulatedContent;
  }
}

export async function ssePost<T = any>(
  url: string,
  data: any,
  options: SSEClientOptions = {}
): Promise<T> {
  const client = new SSEPostClient(url, data, options);
  try {
    return await client.connect();
  } finally {
    client.abort();
  }
}
