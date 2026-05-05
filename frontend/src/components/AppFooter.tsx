import { useState, useEffect } from 'react';
import { Typography, Space, Divider, Badge, Button, Grid, theme, Avatar } from 'antd';
import { GithubOutlined, CopyrightOutlined, HeartFilled, ClockCircleOutlined, GiftOutlined } from '@ant-design/icons';
import { VERSION_INFO, getVersionString } from '../config/version';
import { FEATURE_FLAGS } from '../config/featureFlags';
import { checkLatestVersion } from '../services/versionService';
import { getAuthorProfile, type AuthorProfile } from '../services/authorProfileService';

const { Text, Link } = Typography;
const { useBreakpoint } = Grid;

interface AppFooterProps {
  sidebarWidth?: number;
}

export default function AppFooter({ sidebarWidth = 0 }: AppFooterProps) {
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [hasUpdate, setHasUpdate] = useState(false);
  const [latestVersion, setLatestVersion] = useState('');
  const [releaseUrl, setReleaseUrl] = useState('');
  const [authorProfile, setAuthorProfile] = useState<AuthorProfile | null>(null);
  const { token } = theme.useToken();
  const alphaColor = (color: string, alpha: number) => `color-mix(in srgb, ${color} ${(alpha * 100).toFixed(0)}%, transparent)`;

  useEffect(() => {
    // 检查版本更新（每次都重新检查）
    const checkVersion = async () => {
      try {
        const result = await checkLatestVersion();
        setHasUpdate(result.hasUpdate);
        setLatestVersion(result.latestVersion);
        setReleaseUrl(result.releaseUrl);
      } catch {
        // 静默失败
      }
    };

    // 延迟3秒后检查，避免影响首次加载
    const timer = setTimeout(checkVersion, 3000);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    getAuthorProfile()
      .then(setAuthorProfile)
      .catch(() => {
        // 静默失败，使用构建时作者信息
      });
  }, []);

  // 点击版本号查看更新
  const handleVersionClick = () => {
    if (hasUpdate && releaseUrl) {
      window.open(releaseUrl, '_blank');
    }
  };

  // 计算左边距：桌面端有侧边栏时需要偏移
  const leftOffset = isMobile ? 0 : sidebarWidth;
  const authorName = authorProfile?.display_name || VERSION_INFO.author;
  const authorUrl = authorProfile?.profile_url || VERSION_INFO.authorUrl;
  const authorAvatar = authorProfile?.avatar_url || undefined;

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 0,
        left: leftOffset,
        right: 0,
        backdropFilter: 'blur(20px) saturate(180%)',
        WebkitBackdropFilter: 'blur(20px) saturate(180%)',
        borderTop: `1px solid ${token.colorBorder}`,
        padding: isMobile ? '8px 12px' : '10px 16px',
        zIndex: 100,
        boxShadow: `0 -2px 16px ${alphaColor(token.colorText, 0.08)}`,
        backgroundColor: alphaColor(token.colorBgContainer, 0.82), // 半透明背景以支持 backdrop-filter
        transition: 'left 0.3s ease', // 平滑过渡
      }}
    >
      <div
        style={{
          maxWidth: 1400,
          margin: '0 auto',
          textAlign: 'center',
        }}
      >
        {isMobile ? (
          // 移动端：紧凑单行布局
          <div style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            gap: 8,
            flexWrap: 'wrap'
          }}>
            <Badge dot={hasUpdate} offset={[-8, 2]}>
              <Text
                onClick={handleVersionClick}
                style={{
                  fontSize: 11,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  color: token.colorPrimary,
                  cursor: hasUpdate ? 'pointer' : 'default',
                }}
                title={hasUpdate ? `发现新版本 v${latestVersion}，点击查看` : '当前版本'}
              >
                <strong style={{ color: token.colorText }}>{VERSION_INFO.projectName}</strong>
                <span>{getVersionString()}</span>
              </Text>
            </Badge>
            {FEATURE_FLAGS.sponsor && (
              <>
                <Divider type="vertical" style={{ margin: '0 4px', borderColor: token.colorBorder }} />
                <Button
                  type="text"
                  size="small"
                  icon={<GiftOutlined />}
                  onClick={() => window.open('https://mumuverse.space:1588/', '_blank')}
                  style={{
                    color: token.colorTextSecondary,
                    fontSize: 11,
                    height: 24,
                    padding: '0 4px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  赞助
                </Button>
              </>
            )}
            <Divider type="vertical" style={{ margin: '0 4px', borderColor: token.colorBorder }} />
            <Link
              href={VERSION_INFO.githubUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontSize: 11,
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                color: token.colorTextSecondary,
              }}
            >
              <GithubOutlined style={{ fontSize: 12 }} />
            </Link>
            <Text
              style={{
                fontSize: 10,
                color: token.colorTextTertiary,
              }}
            >
              <ClockCircleOutlined style={{ fontSize: 10, marginRight: 4 }} />
              {VERSION_INFO.buildTime}
            </Text>
          </div>
        ) : (
          // PC端：完整布局
          <Space
            direction="horizontal"
            size={12}
            split={<Divider type="vertical" style={{ borderColor: token.colorBorder }} />}
            style={{
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center'
            }}
          >
            {/* 版本信息 */}
            <Badge dot={hasUpdate} offset={[-8, 2]}>
              <Text
                onClick={handleVersionClick}
                style={{
                  fontSize: 12,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  color: token.colorTextSecondary,
                  textShadow: 'none',
                  cursor: hasUpdate ? 'pointer' : 'default',
                  transition: 'all 0.3s',
                }}
                onMouseEnter={(e) => {
                  if (hasUpdate) {
                    e.currentTarget.style.transform = 'scale(1.05)';
                  }
                }}
                onMouseLeave={(e) => {
                  if (hasUpdate) {
                    e.currentTarget.style.transform = 'scale(1)';
                  }
                }}
                title={hasUpdate ? `发现新版本 v${latestVersion}，点击查看` : '当前版本'}
              >
                <strong style={{ color: token.colorText }}>{VERSION_INFO.projectName}</strong>
                <span>{getVersionString()}</span>
              </Text>
            </Badge>

            {/* GitHub 链接 */}
            <Link
              href={VERSION_INFO.githubUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontSize: 12,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                color: token.colorTextSecondary,
              }}
            >
              <GithubOutlined style={{ fontSize: 13 }} />
              <span>GitHub</span>
            </Link>

            {/* LinuxDO 社区 */}
            <Link
              href={VERSION_INFO.linuxDoUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontSize: 12,
                color: token.colorTextSecondary,
              }}
            >
              LinuxDO 社区
            </Link>

            {FEATURE_FLAGS.sponsor && (
              <Button
                type="primary"
                icon={<GiftOutlined style={{ fontSize: 14 }} />}
                onClick={() => window.open('https://mumuverse.space:1588/', '_blank')}
                style={{
                  background: token.colorPrimary,
                  border: 'none',
                  boxShadow: `0 4px 12px ${alphaColor(token.colorPrimary, 0.35)}`,
                  fontSize: 13,
                  height: 32,
                  padding: '0 20px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  fontWeight: 600,
                  transition: 'all 0.3s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = 'translateY(-2px)';
                  e.currentTarget.style.boxShadow = `0 6px 16px ${alphaColor(token.colorPrimary, 0.5)}`;
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = 'translateY(0)';
                  e.currentTarget.style.boxShadow = `0 4px 12px ${alphaColor(token.colorPrimary, 0.35)}`;
                }}
              >
                赞助支持
              </Button>
            )}

            {/* 许可证 */}
            <Link
              href={VERSION_INFO.licenseUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontSize: 12,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                color: token.colorTextSecondary,
              }}
            >
              <CopyrightOutlined style={{ fontSize: 11 }} />
              <span>{VERSION_INFO.license}</span>
            </Link>

            {/* 更新时间 */}
            <Text
              style={{
                fontSize: 12,
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                color: token.colorTextTertiary,
              }}
            >
              <ClockCircleOutlined style={{ fontSize: 12 }} />
              <span>{VERSION_INFO.buildTime}</span>
            </Text>

            {/* 致谢信息 */}
            <Link
              href={authorUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontSize: 12,
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                color: token.colorTextSecondary,
                textShadow: `0 1px 3px ${alphaColor(token.colorText, 0.08)}`,
              }}
            >
              <span>Made with</span>
              <HeartFilled style={{ color: token.colorError, fontSize: 11 }} />
              <span>by {authorName}</span>
              {authorAvatar && <Avatar size={16} src={authorAvatar} />}
            </Link>
          </Space>
        )}
      </div>

    </div>
  );
}
