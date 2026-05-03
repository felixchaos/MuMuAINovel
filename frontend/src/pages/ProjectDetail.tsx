import { useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate, Outlet, Link, useLocation } from 'react-router-dom';
import { Layout, Menu, Spin, Button, Drawer, theme } from 'antd';
import {
  ArrowLeftOutlined,
  FileTextOutlined,
  TeamOutlined,
  BookOutlined,
  // ToolOutlined,
  GlobalOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  ApartmentOutlined,
  BankOutlined,
  EditOutlined,
  FundOutlined,
  HeartOutlined,
  TrophyOutlined,
  BulbOutlined,
  ClusterOutlined,
  CloudOutlined,
  MoonOutlined,
} from '@ant-design/icons';
import { useStore } from '../store';
import { useCharacterSync, useOutlineSync, useChapterSync } from '../store/hooks';
import { projectApi } from '../services/api';
import ThemeSwitch from '../components/ThemeSwitch';
import { useThemeMode } from '../theme/useThemeMode';
import { getStoredSidebarCollapsed, setStoredSidebarCollapsed } from '../utils/sidebarState';
import FloatingTaskPanel from '../components/FloatingTaskPanel';

const { Header, Sider, Content } = Layout;

// 判断是否为移动端
const isMobile = () => window.innerWidth <= 768;

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState<boolean>(() => getStoredSidebarCollapsed());
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [mobile, setMobile] = useState(isMobile());
  const { token } = theme.useToken();
  const alphaColor = (color: string, alpha: number) => `color-mix(in srgb, ${color} ${(alpha * 100).toFixed(0)}%, transparent)`;
  const { mode, resolvedMode, setMode } = useThemeMode();
  const cycleThemeMode = () => {
    const nextMode = mode === 'light' ? 'dark' : mode === 'dark' ? 'system' : 'light';
    setMode(nextMode);
  };
  const collapsedThemeIcon = mode === 'light' ? <BulbOutlined /> : mode === 'dark' ? <MoonOutlined /> : <CloudOutlined />;

  // 监听窗口大小变化
  useEffect(() => {
    const handleResize = () => {
      setMobile(isMobile());
      if (!isMobile()) {
        setDrawerVisible(false);
      }
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    setStoredSidebarCollapsed(collapsed);
  }, [collapsed]);
  const {
    currentProject,
    setCurrentProject,
    clearProjectData,
    loading,
    setLoading,
    outlines,
    characters,
    chapters,
  } = useStore();

  // 使用同步 hooks
  const { refreshCharacters } = useCharacterSync();
  const { refreshOutlines } = useOutlineSync();
  const { refreshChapters } = useChapterSync();

  useEffect(() => {
    const loadProjectData = async (id: string) => {
      try {
        setLoading(true);
        // 加载项目基本信息
        const project = await projectApi.getProject(id);
        setCurrentProject(project);

        // 并行加载其他数据
        await Promise.all([
          refreshOutlines(id),
          refreshCharacters(id),
          refreshChapters(id),
        ]);
      } catch (error) {
        console.error('加载项目数据失败:', error);
      } finally {
        setLoading(false);
      }
    };

    if (projectId) {
      loadProjectData(projectId);
    }

    return () => {
      clearProjectData();
    };
  }, [projectId, clearProjectData, setLoading, setCurrentProject, refreshOutlines, refreshCharacters, refreshChapters]);

  // 移除事件监听，避免无限循环
  // Hook 内部已经更新了 store，不需要再次刷新

  const menuItems = [
    {
      key: 'sponsor',
      icon: <HeartOutlined />,
      label: <Link to={`/project/${projectId}/sponsor`}>赞助支持</Link>,
    },
    {
      type: 'group' as const,
      label: '创作管理',
      children: [
        {
          key: 'world-setting',
          icon: <GlobalOutlined />,
          label: <Link to={`/project/${projectId}/world-setting`}>世界设定</Link>,
        },
        {
          key: 'characters',
          icon: <TeamOutlined />,
          label: <Link to={`/project/${projectId}/characters`}>角色管理</Link>,
        },
        {
          key: 'organizations',
          icon: <BankOutlined />,
          label: <Link to={`/project/${projectId}/organizations`}>组织管理</Link>,
        },
        {
          key: 'careers',
          icon: <TrophyOutlined />,
          label: <Link to={`/project/${projectId}/careers`}>职业管理</Link>,
        },
        {
          key: 'relationships',
          icon: <ApartmentOutlined />,
          label: <Link to={`/project/${projectId}/relationships`}>关系管理</Link>,
        },
        {
          key: 'outline',
          icon: <FileTextOutlined />,
          label: <Link to={`/project/${projectId}/outline`}>大纲管理</Link>,
        },
        {
          key: 'chapters',
          icon: <BookOutlined />,
          label: <Link to={`/project/${projectId}/chapters`}>章节管理</Link>,
        },
        {
          key: 'chapter-analysis',
          icon: <FundOutlined />,
          label: <Link to={`/project/${projectId}/chapter-analysis`}>剧情分析</Link>,
        },
        {
          key: 'story-engine',
          icon: <ClusterOutlined />,
          label: <Link to={`/project/${projectId}/story-engine`}>剧情工程</Link>,
        },
        {
          key: 'foreshadows',
          icon: <BulbOutlined />,
          label: <Link to={`/project/${projectId}/foreshadows`}>伏笔管理</Link>,
        },
      ],
    },
    {
      type: 'group' as const,
      label: '创作工具',
      children: [
        {
          key: 'writing-styles',
          icon: <EditOutlined />,
          label: <Link to={`/project/${projectId}/writing-styles`}>写作风格</Link>,
        },
        {
          key: 'prompt-workshop',
          icon: <CloudOutlined />,
          label: <Link to={`/project/${projectId}/prompt-workshop`}>提示词工坊</Link>,
        },
      ],
    },
  ];

  const menuItemsCollapsed = [
    {
      key: 'sponsor',
      icon: <HeartOutlined />,
      label: <Link to={`/project/${projectId}/sponsor`}>赞助支持</Link>,
    },
    {
      key: 'world-setting',
      icon: <GlobalOutlined />,
      label: <Link to={`/project/${projectId}/world-setting`}>世界设定</Link>,
    },
    {
      key: 'careers',
      icon: <TrophyOutlined />,
      label: <Link to={`/project/${projectId}/careers`}>职业管理</Link>,
    },
    {
      key: 'characters',
      icon: <TeamOutlined />,
      label: <Link to={`/project/${projectId}/characters`}>角色管理</Link>,
    },
    {
      key: 'relationships',
      icon: <ApartmentOutlined />,
      label: <Link to={`/project/${projectId}/relationships`}>关系管理</Link>,
    },
    {
      key: 'organizations',
      icon: <BankOutlined />,
      label: <Link to={`/project/${projectId}/organizations`}>组织管理</Link>,
    },
    {
      key: 'outline',
      icon: <FileTextOutlined />,
      label: <Link to={`/project/${projectId}/outline`}>大纲管理</Link>,
    },
    {
      key: 'chapters',
      icon: <BookOutlined />,
      label: <Link to={`/project/${projectId}/chapters`}>章节管理</Link>,
    },
    {
      key: 'chapter-analysis',
      icon: <FundOutlined />,
      label: <Link to={`/project/${projectId}/chapter-analysis`}>剧情分析</Link>,
    },
    {
      key: 'story-engine',
      icon: <ClusterOutlined />,
      label: <Link to={`/project/${projectId}/story-engine`}>剧情工程</Link>,
    },
    {
      key: 'foreshadows',
      icon: <BulbOutlined />,
      label: <Link to={`/project/${projectId}/foreshadows`}>伏笔管理</Link>,
    },
    {
      key: 'writing-styles',
      icon: <EditOutlined />,
      label: <Link to={`/project/${projectId}/writing-styles`}>写作风格</Link>,
    },
    {
      key: 'prompt-workshop',
      icon: <CloudOutlined />,
      label: <Link to={`/project/${projectId}/prompt-workshop`}>提示词工坊</Link>,
    },
  ];

  // 根据当前路径动态确定选中的菜单项
  const selectedKey = useMemo(() => {
    const path = location.pathname;
    if (path.includes('/world-setting')) return 'world-setting';
    if (path.includes('/careers')) return 'careers';
    if (path.includes('/relationships')) return 'relationships';
    if (path.includes('/organizations')) return 'organizations';
    if (path.includes('/outline')) return 'outline';
    if (path.includes('/characters')) return 'characters';
    if (path.includes('/chapter-analysis')) return 'chapter-analysis';
    if (path.includes('/story-engine')) return 'story-engine';
    if (path.includes('/foreshadows')) return 'foreshadows';
    if (path.includes('/chapters')) return 'chapters';
    if (path.includes('/writing-styles')) return 'writing-styles';
    if (path.includes('/prompt-workshop')) return 'prompt-workshop';
    if (path.includes('/sponsor')) return 'sponsor';
    // if (path.includes('/polish')) return 'polish';
    return 'sponsor'; // 默认选中赞助支持
  }, [location.pathname]);

  if (loading || !currentProject) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" />
      </div>
    );
  }

  // 渲染菜单内容
  const renderMenu = () => (
    <div style={{
      flex: 1,
      overflowY: 'auto',
      overflowX: 'hidden'
    }}>
      <Menu
        mode="inline"
        inlineCollapsed={collapsed}
        selectedKeys={[selectedKey]}
        style={{
          borderRight: 0,
          paddingTop: '12px'
        }}
        items={collapsed ? menuItemsCollapsed : menuItems}
        onClick={() => mobile && setDrawerVisible(false)}
      />
    </div>
  );

  return (
    <Layout style={{ minHeight: '100vh', height: '100vh', overflow: 'hidden' }}>
      <Header style={{
        background: token.colorPrimary,
        padding: mobile ? '0 12px' : '0 24px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        position: 'fixed',
        top: 0,
        left: mobile ? 0 : (collapsed ? 60 : 220),
        right: 0,
        zIndex: 1000,
        boxShadow: `0 2px 10px ${alphaColor(token.colorText, 0.16)}`,
        height: mobile ? 56 : 70,
        transition: 'left 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
        overflow: 'hidden'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', zIndex: 1 }}>
          {mobile && (
            <Button
              type="text"
              icon={<MenuUnfoldOutlined />}
              onClick={() => setDrawerVisible(true)}
              style={{
                fontSize: '18px',
                color: token.colorWhite,
                width: '36px',
                height: '36px'
              }}
            />
          )}
        </div>

        <h2 style={{
          margin: 0,
          color: token.colorWhite,
          fontSize: mobile ? '16px' : '24px',
          fontWeight: 600,
          textShadow: `0 2px 4px ${alphaColor(token.colorText, 0.2)}`,
          position: mobile ? 'static' : 'absolute',
          left: mobile ? 'auto' : '50%',
          transform: mobile ? 'none' : 'translateX(-50%)',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          flex: mobile ? 1 : 'none',
          textAlign: mobile ? 'center' : 'left',
          paddingLeft: mobile ? '8px' : '0',
          paddingRight: mobile ? '8px' : '0'
        }}>
          {currentProject.title}
        </h2>

        {mobile && (
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/')}
            style={{
              fontSize: '14px',
              color: token.colorWhite,
              height: '36px',
              padding: '0 8px',
              zIndex: 1
            }}
          >
            主页
          </Button>
        )}

        {!mobile && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', zIndex: 1 }}>
            <div style={{ display: 'flex', gap: '16px' }}>
              {[
                { label: '大纲', value: outlines.length, unit: '条' },
                { label: '角色', value: characters.length, unit: '个' },
                { label: '章节', value: chapters.length, unit: '章' },
                { label: '已写', value: currentProject.current_words, unit: '字' },
              ].map((item, index) => (
                <div
                  key={index}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    backdropFilter: 'blur(4px)',
                    borderRadius: '28px',
                    minWidth: '56px',
                    height: '56px',
                    padding: '0 12px',
                    boxShadow: `inset 0 0 15px ${alphaColor(token.colorWhite, 0.15)}, 0 4px 10px ${alphaColor(token.colorText, 0.1)}`,
                    cursor: 'default',
                    transition: 'all 0.3s ease',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = 'translateY(-3px) scale(1.02)';
                    e.currentTarget.style.boxShadow = `inset 0 0 20px ${alphaColor(token.colorWhite, 0.25)}, 0 8px 16px ${alphaColor(token.colorText, 0.15)}`;
                    e.currentTarget.style.border = `1px solid ${alphaColor(token.colorWhite, 0.1)}`;
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = 'translateY(0) scale(1)';
                    e.currentTarget.style.boxShadow = `inset 0 0 15px ${alphaColor(token.colorWhite, 0.15)}, 0 4px 10px ${alphaColor(token.colorText, 0.1)}`;
                  }}
                >
                  <span style={{
                    fontSize: '11px',
                    color: alphaColor(token.colorWhite, 0.9),
                    marginBottom: '2px',
                    lineHeight: 1
                  }}>
                    {item.label}
                  </span>
                  <span style={{
                    fontSize: '15px',
                    fontWeight: '600',
                    color: token.colorWhite,
                    lineHeight: 1,
                    fontFamily: 'Monaco, monospace'
                  }}>
                    {item.value > 10000 ? (item.value / 10000).toFixed(1) + 'w' : item.value}
                    <span style={{ fontSize: '10px', marginLeft: '2px', opacity: 0.8 }}>{item.unit}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Header>

      <Layout style={{ marginTop: mobile ? 56 : 70 }}>
        {mobile ? (
          <Drawer
            title={
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{
                  width: 30,
                  height: 30,
                  background: token.colorPrimary,
                  borderRadius: 8,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: token.colorWhite,
                  fontSize: 16,
                }}>
                  <BookOutlined />
                </div>
                <span style={{ fontWeight: 600, fontSize: 16 }}>MuMuAINovel</span>
              </div>
            }
            placement="left"
            onClose={() => setDrawerVisible(false)}
            open={drawerVisible}
            width={280}
            styles={{ body: { padding: 0, display: 'flex', flexDirection: 'column' } }}
          >
            {renderMenu()}
            <div style={{ padding: 16, borderTop: `1px solid ${token.colorBorderSecondary}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12, color: token.colorTextTertiary, marginBottom: 8 }}>
                <span>主题模式</span>
                <span>{resolvedMode === 'dark' ? '深色' : '浅色'}</span>
              </div>
              <ThemeSwitch block />
            </div>
          </Drawer>
        ) : (
          <Sider
            collapsible
            collapsed={collapsed}
            onCollapse={setCollapsed}
            trigger={null}
            width={220}
            collapsedWidth={60}
            style={{
              position: 'fixed',
              left: 0,
              top: 0,
              bottom: 0,
              overflow: 'hidden',
              transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
              height: '100vh',
              background: token.colorBgContainer,
              borderRight: `1px solid ${token.colorBorderSecondary}`,
              boxShadow: `4px 0 16px ${alphaColor(token.colorText, 0.06)}`,
              zIndex: 1000
            }}
          >
            <div style={{
              height: '100%',
              display: 'flex',
              flexDirection: 'column'
            }}>
              <div style={{
                height: 70,
                display: 'flex',
                alignItems: 'center',
                padding: collapsed ? 0 : '0 12px',
                background: token.colorPrimary,
                flexShrink: 0,
                justifyContent: collapsed ? 'center' : 'space-between',
                gap: 8
              }}>
                {collapsed ? (
                  <Button
                    type="text"
                    icon={<MenuUnfoldOutlined />}
                    onClick={() => setCollapsed(false)}
                    style={{
                      color: token.colorWhite,
                      width: '100%',
                      height: '100%',
                      padding: 0,
                      borderRadius: 0,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center'
                    }}
                  />
                ) : (
                  <>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0, overflow: 'hidden' }}>
                      <div style={{
                        width: 30,
                        height: 30,
                        background: alphaColor(token.colorWhite, 0.2),
                        borderRadius: 8,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: token.colorWhite,
                        fontSize: 16,
                        backdropFilter: 'blur(4px)'
                      }}>
                        <BookOutlined />
                      </div>
                      <span style={{
                        color: token.colorWhite,
                        fontWeight: 600,
                        fontSize: 15,
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis'
                      }}>
                        MuMuAINovel
                      </span>
                    </div>
                    <Button
                      type="text"
                      icon={<MenuFoldOutlined />}
                      onClick={() => setCollapsed(true)}
                      style={{
                        color: token.colorWhite,
                        width: 32,
                        height: 32,
                        padding: 0,
                        flexShrink: 0
                      }}
                    />
                  </>
                )}
              </div>
              {renderMenu()}
              <div style={{
                padding: collapsed ? '12px 8px' : '12px',
                borderTop: `1px solid ${token.colorBorderSecondary}`,
                flexShrink: 0
              }}>
                {collapsed ? (
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
                    <Button
                      type="text"
                      icon={collapsedThemeIcon}
                      onClick={cycleThemeMode}
                      title={`主题模式：${mode === 'light' ? '浅色' : mode === 'dark' ? '深色' : '跟随系统'}（点击切换）`}
                      style={{
                        width: 40,
                        height: 40,
                        borderRadius: 20,
                        background: alphaColor(token.colorBgContainer, 0.65),
                        border: `1px solid ${token.colorBorder}`,
                        color: token.colorText,
                        padding: 0,
                      }}
                    />
                    <Button
                      type="text"
                      icon={<ArrowLeftOutlined />}
                      onClick={() => navigate('/')}
                      style={{
                        width: 40,
                        height: 40,
                        borderRadius: 20,
                        background: alphaColor(token.colorBgContainer, 0.65),
                        border: `1px solid ${token.colorBorder}`,
                        color: token.colorText,
                        padding: 0,
                      }}
                    />
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12, color: token.colorTextTertiary }}>
                      <span>主题模式</span>
                      <span>{resolvedMode === 'dark' ? '深色' : '浅色'}</span>
                    </div>
                    <ThemeSwitch block />
                    <Button
                      type="text"
                      icon={<ArrowLeftOutlined />}
                      onClick={() => navigate('/')}
                      block
                      style={{
                        color: token.colorText,
                        height: 40,
                        justifyContent: 'flex-start',
                        padding: '0 12px'
                      }}
                    >
                      返回主页
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </Sider>
        )}

        <Layout style={{
          marginLeft: mobile ? 0 : (collapsed ? 60 : 220),
          transition: 'margin-left 0.3s cubic-bezier(0.4, 0, 0.2, 1)'
        }}>
          <Content
            style={{
              background: token.colorBgLayout,
              padding: mobile ? 12 : 24,
              height: mobile ? 'calc(100vh - 56px)' : 'calc(100vh - 70px)',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column'
            }}
          >
            <div style={{
              background: token.colorBgContainer,
              padding: mobile ? 12 : 24,
              borderRadius: mobile ? '8px' : '12px',
              boxShadow: `0 8px 24px ${alphaColor(token.colorText, 0.08)}`,
              height: '100%',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column'
            }}>
              <Outlet />
            </div>
          </Content>
        </Layout>
      </Layout>

      {/* 悬浮任务框 */}
      {projectId && <FloatingTaskPanel projectId={projectId} />}
    </Layout>
  );
}
