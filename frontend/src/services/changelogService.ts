/**
 * GitHub 提交日志获取服务
 * 用于从 GitHub API 获取项目的提交历史并转换为更新日志
 */
import { VERSION_INFO } from '../config/version';

export interface GitHubCommit {
  sha: string;
  commit: {
    author: {
      name: string;
      email: string;
      date: string;
    };
    message: string;
  };
  html_url: string;
  author: {
    login: string;
    avatar_url: string;
  } | null;
}

export interface ChangelogEntry {
  id: string;
  date: string;
  version?: string;
  author: {
    name: string;
    avatar?: string;
    username?: string;
  };
  message: string;
  commitUrl: string;
  type: 'feature' | 'fix' | 'docs' | 'style' | 'refactor' | 'perf' | 'test' | 'chore' | 'update' | 'other';
  scope?: string;
}

const GITHUB_API_BASE = 'https://api.github.com';
const REPO_OWNER = VERSION_INFO.githubOwner;
const REPO_NAME = VERSION_INFO.githubRepo;
const REPO_BRANCH = VERSION_INFO.githubBranch;
const CHANGELOG_CACHE_SCOPE = `${REPO_OWNER}/${REPO_NAME}:${REPO_BRANCH}`;
const CHANGELOG_LAST_FETCH_KEY = `changelog_last_fetch:${CHANGELOG_CACHE_SCOPE}`;
const CHANGELOG_CACHE_KEY = `changelog_cache:${CHANGELOG_CACHE_SCOPE}`;

/**
 * 提交类型映射表
 * 统一不同别名到标准类型
 */
const TYPE_MAPPING: Record<string, ChangelogEntry['type']> = {
  // 功能类
  'feat': 'feature',
  'feature': 'feature',
  'update': 'update',
  
  // 修复类
  'fix': 'fix',
  
  // 文档类
  'docs': 'docs',
  'doc': 'docs',
  
  // 样式类
  'style': 'style',
  
  // 重构类
  'refactor': 'refactor',
  
  // 性能类
  'perf': 'perf',
  
  // 测试类
  'test': 'test',
  
  // 杂项类
  'chore': 'chore',
};

/**
 * 从提交信息中解析类型和作用域
 *
 * 匹配优先级（从高到低）：
 * 1. 标准 Conventional Commits 格式: type(scope): message 或 type: message
 * 2. 方括号格式: [type] message
 * 3. 简单前缀格式: type: message（支持中文冒号）
 * 4. 关键词模糊匹配（中英文）
 */
function parseCommitType(message: string): { type: ChangelogEntry['type']; scope?: string; cleanMessage: string } {
  const lowerMessage = message.toLowerCase().trim();
  
  // 优先级1：标准 Conventional Commits 格式 - type(scope): message 或 type: message
  // 匹配所有支持的类型
  const conventionalPattern = new RegExp(
    `^(${Object.keys(TYPE_MAPPING).join('|')})(?:\\(([^)]+)\\))?\\s*[:\\:：]\\s*(.+)`,
    'i'
  );
  const conventionalMatch = message.match(conventionalPattern);
  if (conventionalMatch) {
    const typeStr = conventionalMatch[1].toLowerCase();
    const mappedType = TYPE_MAPPING[typeStr] || 'other';
    return {
      type: mappedType,
      scope: conventionalMatch[2],
      cleanMessage: conventionalMatch[3].trim(),
    };
  }

  // 优先级2：方括号格式 - [type] message
  const bracketPattern = new RegExp(
    `^\\[(${Object.keys(TYPE_MAPPING).join('|')})\\]\\s*(.+)`,
    'i'
  );
  const bracketMatch = message.match(bracketPattern);
  if (bracketMatch) {
    const typeStr = bracketMatch[1].toLowerCase();
    const mappedType = TYPE_MAPPING[typeStr] || 'other';
    return {
      type: mappedType,
      cleanMessage: bracketMatch[2].trim(),
    };
  }

  // 优先级3：简单前缀格式 - type: message（支持英文和中文冒号）
  for (const [key, value] of Object.entries(TYPE_MAPPING)) {
    const prefixPattern = new RegExp(`^${key}\\s*[:\\:：]\\s*`, 'i');
    if (prefixPattern.test(lowerMessage)) {
      const cleanMsg = message.replace(prefixPattern, '').trim();
      return { type: value, cleanMessage: cleanMsg };
    }
  }

  // 优先级4：关键词模糊匹配（仅当前面都不匹配时）
  const keywordMap: Array<{ keywords: string[]; type: ChangelogEntry['type'] }> = [
    { keywords: ['修复', 'fix'], type: 'fix' },
    { keywords: ['优化', 'perf'], type: 'perf' },
    { keywords: ['文档', 'document'], type: 'docs' },
    { keywords: ['新增', '添加', '增加', 'add'], type: 'feature' },
    { keywords: ['更新', 'update'], type: 'update' },
    { keywords: ['样式', 'style'], type: 'style' },
    { keywords: ['重构', 'refactor'], type: 'refactor' },
    { keywords: ['测试', 'test'], type: 'test' },
  ];

  for (const { keywords, type } of keywordMap) {
    if (keywords.some(keyword => lowerMessage.includes(keyword))) {
      return { type, cleanMessage: message };
    }
  }

  // 默认类型
  return { type: 'other', cleanMessage: message };
}

/**
 * 获取GitHub提交历史
 */
export async function fetchGitHubCommits(page: number = 1, perPage: number = 30): Promise<GitHubCommit[]> {
  try {
    const params = new URLSearchParams({
      sha: REPO_BRANCH,
      page: String(page),
      per_page: String(perPage),
    });
    const url = `${GITHUB_API_BASE}/repos/${REPO_OWNER}/${REPO_NAME}/commits?${params.toString()}`;
    
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Accept': 'application/vnd.github.v3+json',
      },
      cache: 'no-cache',
    });

    if (!response.ok) {
      throw new Error(`GitHub API 请求失败: ${response.status} ${response.statusText}`);
    }

    return await response.json();
  } catch (error) {
    console.error('获取 GitHub 提交历史失败:', error);
    throw error;
  }
}

/**
 * 将GitHub提交转换为更新日志条目
 */
export function convertCommitsToChangelog(commits: GitHubCommit[]): ChangelogEntry[] {
  return commits.map(commit => {
    const { type, scope, cleanMessage } = parseCommitType(commit.commit.message);
    
    return {
      id: commit.sha,
      date: commit.commit.author.date,
      author: {
        name: commit.commit.author.name,
        avatar: commit.author?.avatar_url,
        username: commit.author?.login,
      },
      message: cleanMessage,
      commitUrl: commit.html_url,
      type,
      scope,
    };
  });
}

/**
 * 获取格式化的更新日志
 */
export async function fetchChangelog(page: number = 1, perPage: number = 30): Promise<ChangelogEntry[]> {
  const commits = await fetchGitHubCommits(page, perPage);
  return convertCommitsToChangelog(commits);
}

/**
 * 按日期分组更新日志
 */
export function groupChangelogByDate(entries: ChangelogEntry[]): Map<string, ChangelogEntry[]> {
  const grouped = new Map<string, ChangelogEntry[]>();
  
  entries.forEach(entry => {
    const date = new Date(entry.date).toISOString().split('T')[0];
    const existing = grouped.get(date) || [];
    existing.push(entry);
    grouped.set(date, existing);
  });
  
  return grouped;
}

/**
 * 检查是否应该获取更新日志（避免频繁请求）
 */
export function shouldFetchChangelog(): boolean {
  const lastFetch = localStorage.getItem(CHANGELOG_LAST_FETCH_KEY);
  
  if (!lastFetch) {
    return true;
  }
  
  const lastFetchTime = new Date(lastFetch).getTime();
  const now = Date.now();
  const oneHourMs = 60 * 60 * 1000; // 1小时
  
  return now - lastFetchTime >= oneHourMs;
}

/**
 * 记录更新日志获取时间
 */
export function markChangelogFetched(): void {
  localStorage.setItem(CHANGELOG_LAST_FETCH_KEY, new Date().toISOString());
}

/**
 * 获取缓存的更新日志
 */
export function getCachedChangelog(): ChangelogEntry[] | null {
  const cached = localStorage.getItem(CHANGELOG_CACHE_KEY);
  if (cached) {
    try {
      return JSON.parse(cached);
    } catch {
      return null;
    }
  }
  return null;
}

/**
 * 缓存更新日志
 */
export function cacheChangelog(entries: ChangelogEntry[]): void {
  localStorage.setItem(CHANGELOG_CACHE_KEY, JSON.stringify(entries));
}

/**
 * 清除更新日志缓存
 * 用于强制刷新数据
 */
export function clearChangelogCache(): void {
  localStorage.removeItem(CHANGELOG_CACHE_KEY);
  localStorage.removeItem(CHANGELOG_LAST_FETCH_KEY);
  localStorage.removeItem('changelog_cache');
  localStorage.removeItem('changelog_last_fetch');
}
