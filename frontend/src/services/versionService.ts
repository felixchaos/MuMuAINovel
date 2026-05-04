import { VERSION_INFO } from '../config/version';

interface VersionCheckResult {
  hasUpdate: boolean;
  latestVersion: string;
  releaseUrl: string;
}

/**
 * 比较版本号
 * @returns -1: v1 < v2, 0: v1 = v2, 1: v1 > v2
 */
function compareVersion(v1: string, v2: string): number {
  const parts1 = v1.split('.').map(Number);
  const parts2 = v2.split('.').map(Number);
  
  for (let i = 0; i < Math.max(parts1.length, parts2.length); i++) {
    const num1 = parts1[i] || 0;
    const num2 = parts2[i] || 0;
    
    if (num1 < num2) return -1;
    if (num1 > num2) return 1;
  }
  
  return 0;
}

/**
 * 使用 shields.io Badge API 获取最新版本
 * 优点：无 CORS 问题，自动从 GitHub 获取，无需维护
 */
export async function checkLatestVersion(): Promise<VersionCheckResult> {
  try {
    // 使用 shields.io 的 GitHub release badge API
    const badgeUrl = `https://img.shields.io/github/v/release/${VERSION_INFO.githubOwner}/${VERSION_INFO.githubRepo}`;
    
    const response = await fetch(badgeUrl, {
      method: 'GET',
      cache: 'no-cache',
    });
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} ${response.statusText}`);
    }
    
    // shields.io 返回的是 SVG 格式
    const svgText = await response.text();
    
    // 从 SVG 中提取版本号
    // SVG 中版本号通常在 <text> 标签内，格式如: v1.0.0 或 1.0.0
    const versionRegex = /v?([\d.]+)/g;
    const matches = svgText.match(versionRegex);
    
    if (matches && matches.length > 0) {
      // 通常最后一个匹配是版本号（前面的可能是标签文本）
      const versionMatch = matches[matches.length - 1];
      const latestVersion = versionMatch.replace('v', '');
      
      // 验证版本号格式 (x.x.x)
      if (/^\d+\.\d+(\.\d+)?$/.test(latestVersion)) {
        const hasUpdate = compareVersion(VERSION_INFO.version, latestVersion) < 0;
        
        return {
          hasUpdate,
          latestVersion,
          releaseUrl: `${VERSION_INFO.githubUrl}/releases/tag/v${latestVersion}`,
        };
      }
    }
    
    throw new Error('无法从 Badge API 解析版本信息');
  } catch {
    // 失败时返回无更新
    return {
      hasUpdate: false,
      latestVersion: VERSION_INFO.version,
      releaseUrl: VERSION_INFO.githubUrl,
    };
  }
}

/**
 * 检查是否应该执行版本检查（避免频繁请求）
 */
export function shouldCheckVersion(): boolean {
  const lastCheck = localStorage.getItem('version_last_check');
  
  if (!lastCheck) {
    return true;
  }
  
  const lastCheckTime = new Date(lastCheck).getTime();
  const now = Date.now();
  const sixHoursMs = 6 * 60 * 60 * 1000; // 6小时
  
  return now - lastCheckTime >= sixHoursMs;
}

/**
 * 记录版本检查时间
 */
export function markVersionChecked(): void {
  localStorage.setItem('version_last_check', new Date().toISOString());
}

/**
 * 获取缓存的版本信息
 */
export function getCachedVersionInfo(): VersionCheckResult | null {
  const cached = localStorage.getItem('version_check_result');
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
 * 缓存版本信息
 */
export function cacheVersionInfo(info: VersionCheckResult): void {
  localStorage.setItem('version_check_result', JSON.stringify(info));
}

/**
 * 用户已查看更新提示
 */
export function markUpdateViewed(version: string): void {
  localStorage.setItem('version_viewed', version);
}

/**
 * 检查用户是否已查看此版本的更新提示
 */
export function hasViewedUpdate(version: string): boolean {
  const viewedVersion = localStorage.getItem('version_viewed');
  
  // 如果已查看的版本低于最新版本，应该显示红点
  if (viewedVersion && version) {
    const parts1 = viewedVersion.split('.').map(Number);
    const parts2 = version.split('.').map(Number);
    
    for (let i = 0; i < Math.max(parts1.length, parts2.length); i++) {
      const num1 = parts1[i] || 0;
      const num2 = parts2[i] || 0;
      
      if (num1 < num2) {
        return false; // 已查看的版本低于最新版本，需要显示红点
      }
      if (num1 > num2) {
        return true; // 已查看的版本高于最新版本
      }
    }
  }
  
  return viewedVersion === version;
}
