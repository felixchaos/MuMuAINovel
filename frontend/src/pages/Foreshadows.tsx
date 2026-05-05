import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams } from 'react-router-dom';
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select,
  InputNumber, Switch, message, Tooltip, Popconfirm, Statistic,
  Row, Col, Empty, Divider, Badge, Alert, Pagination, Dropdown, theme
} from 'antd';
import type { MenuProps } from 'antd';
import {
  PlusOutlined, SyncOutlined, EditOutlined, DeleteOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
  BulbOutlined, EyeOutlined, FlagOutlined, WarningOutlined,
  ClockCircleOutlined, MoreOutlined, ReloadOutlined, InfoCircleOutlined
} from '@ant-design/icons';
import { foreshadowApi, chapterApi, characterApi } from '../services/api';
import type {
  Foreshadow, ForeshadowCreate, ForeshadowUpdate, ForeshadowStats,
  ForeshadowStatus, ForeshadowCategory, Chapter, Character
} from '../types';

const { TextArea } = Input;
const { Option } = Select;

// 状态配置
const STATUS_CONFIG: Record<ForeshadowStatus, { label: string; color: string; icon: React.ReactNode }> = {
  pending: { label: '待埋入', color: 'default', icon: <ClockCircleOutlined /> },
  planted: { label: '已埋入', color: 'green', icon: <BulbOutlined /> },
  resolved: { label: '已回收', color: 'blue', icon: <CheckCircleOutlined /> },
  partially_resolved: { label: '部分回收', color: 'orange', icon: <ExclamationCircleOutlined /> },
  abandoned: { label: '已废弃', color: 'default', icon: <CloseCircleOutlined /> },
};

// 分类配置
const CATEGORY_CONFIG: Record<string, { label: string; color: string }> = {
  identity: { label: '身世', color: 'purple' },
  mystery: { label: '悬念', color: 'magenta' },
  item: { label: '物品', color: 'gold' },
  relationship: { label: '关系', color: 'cyan' },
  event: { label: '事件', color: 'blue' },
  ability: { label: '能力', color: 'green' },
  prophecy: { label: '预言', color: 'volcano' },
};

export default function Foreshadows() {
  const { projectId } = useParams<{ projectId: string }>();
  const [loading, setLoading] = useState(false);
  const [foreshadows, setForeshadows] = useState<Foreshadow[]>([]);
  const [stats, setStats] = useState<ForeshadowStats | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [total, setTotal] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  
  // 筛选条件
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>(undefined);
  const [sourceFilter, setSourceFilter] = useState<string | undefined>(undefined);
  
  // 模态框状态
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [syncModalVisible, setSyncModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [plantModalVisible, setPlantModalVisible] = useState(false);
  const [resolveModalVisible, setResolveModalVisible] = useState(false);
  
  const [currentForeshadow, setCurrentForeshadow] = useState<Foreshadow | null>(null);
  const [form] = Form.useForm();
  const [plantForm] = Form.useForm();
  const [resolveForm] = Form.useForm();
  const [syncing, setSyncing] = useState(false);
  
  // 表格容器引用，用于计算滚动高度
  const tableContainerRef = useRef<HTMLDivElement>(null);
  const [tableScrollY, setTableScrollY] = useState<number>(400);
  const { token } = theme.useToken();

  // 加载伏笔列表
  const loadForeshadows = useCallback(async () => {
    if (!projectId) return;
    
    setLoading(true);
    try {
      const response = await foreshadowApi.getProjectForeshadows(projectId, {
        status: statusFilter,
        category: categoryFilter,
        source_type: sourceFilter,
        page: currentPage,
        limit: pageSize,
      });
      
      setForeshadows(response.items);
      setTotal(response.total);
      if (response.stats) {
        setStats(response.stats);
      }
    } catch (error) {
      console.error('加载伏笔列表失败:', error);
    } finally {
      setLoading(false);
    }
  }, [projectId, statusFilter, categoryFilter, sourceFilter, currentPage, pageSize]);

  // 加载章节列表（用于选择）
  const loadChapters = useCallback(async () => {
    if (!projectId) return;
    try {
      const chaptersData = await chapterApi.getChapters(projectId);
      setChapters(chaptersData);
    } catch (error) {
      console.error('加载章节列表失败:', error);
    }
  }, [projectId]);

  // 加载角色列表（用于关联角色）
  const loadCharacters = useCallback(async () => {
    if (!projectId) return;
    try {
      const charactersData = await characterApi.getCharacters(projectId);
      setCharacters(charactersData);
    } catch (error) {
      console.error('加载角色列表失败:', error);
    }
  }, [projectId]);

  // 加载统计
  const loadStats = useCallback(async () => {
    if (!projectId) return;
    try {
      // 获取当前最大章节号（只计算有内容的章节，与表格显示逻辑保持一致）
      const chaptersWithContent = chapters.filter(c => c.content);
      const maxChapter = chaptersWithContent.length > 0
        ? Math.max(...chaptersWithContent.map(c => c.chapter_number))
        : undefined;
      const statsData = await foreshadowApi.getForeshadowStats(projectId, maxChapter);
      setStats(statsData);
    } catch (error) {
      console.error('加载统计失败:', error);
    }
  }, [projectId, chapters]);

  useEffect(() => {
    loadForeshadows();
    loadChapters();
    loadCharacters();
  }, [loadForeshadows, loadChapters, loadCharacters]);

  // 计算表格滚动高度
  useEffect(() => {
    const calculateTableHeight = () => {
      if (tableContainerRef.current) {
        // 获取容器高度，减去表头高度（约55px）
        const containerHeight = tableContainerRef.current.clientHeight;
        setTableScrollY(Math.max(containerHeight - 55, 200));
      }
    };
    
    calculateTableHeight();
    window.addEventListener('resize', calculateTableHeight);
    
    // 延迟再计算一次，确保布局完成
    const timer = setTimeout(calculateTableHeight, 100);
    
    return () => {
      window.removeEventListener('resize', calculateTableHeight);
      clearTimeout(timer);
    };
  }, [stats]); // stats 变化时重新计算（因为统计卡片高度可能变化）

  useEffect(() => {
    if (chapters.length > 0) {
      loadStats();
    }
  }, [chapters, loadStats]);

  // 创建/编辑伏笔
  const handleSave = async (values: ForeshadowCreate | ForeshadowUpdate) => {
    try {
      if (currentForeshadow) {
        await foreshadowApi.updateForeshadow(currentForeshadow.id, values as ForeshadowUpdate);
        message.success('伏笔更新成功');
      } else {
        await foreshadowApi.createForeshadow({
          ...values,
          project_id: projectId!,
        } as ForeshadowCreate);
        message.success('伏笔创建成功');
      }
      setEditModalVisible(false);
      form.resetFields();
      setCurrentForeshadow(null);
      loadForeshadows();
    } catch (error) {
      console.error('保存伏笔失败:', error);
    }
  };

  // 删除伏笔
  const handleDelete = async (id: string) => {
    try {
      await foreshadowApi.deleteForeshadow(id);
      message.success('伏笔删除成功');
      loadForeshadows();
    } catch (error) {
      console.error('删除伏笔失败:', error);
    }
  };

  // 标记埋入
  const handlePlant = async (values: { chapter_id: string; hint_text?: string }) => {
    if (!currentForeshadow) return;
    
    const chapter = chapters.find(c => c.id === values.chapter_id);
    if (!chapter) return;
    
    try {
      await foreshadowApi.plantForeshadow(currentForeshadow.id, {
        chapter_id: values.chapter_id,
        chapter_number: chapter.chapter_number,
        hint_text: values.hint_text,
      });
      message.success('伏笔已标记为埋入');
      setPlantModalVisible(false);
      plantForm.resetFields();
      setCurrentForeshadow(null);
      loadForeshadows();
    } catch (error) {
      console.error('标记埋入失败:', error);
    }
  };

  // 标记回收
  const handleResolve = async (values: { chapter_id: string; resolution_text?: string; is_partial?: boolean }) => {
    if (!currentForeshadow) return;
    
    const chapter = chapters.find(c => c.id === values.chapter_id);
    if (!chapter) return;
    
    try {
      await foreshadowApi.resolveForeshadow(currentForeshadow.id, {
        chapter_id: values.chapter_id,
        chapter_number: chapter.chapter_number,
        resolution_text: values.resolution_text,
        is_partial: values.is_partial,
      });
      message.success('伏笔已标记为回收');
      setResolveModalVisible(false);
      resolveForm.resetFields();
      setCurrentForeshadow(null);
      loadForeshadows();
    } catch (error) {
      console.error('标记回收失败:', error);
    }
  };

  // 标记废弃
  const handleAbandon = async (id: string) => {
    try {
      await foreshadowApi.abandonForeshadow(id);
      message.success('伏笔已标记为废弃');
      loadForeshadows();
    } catch (error) {
      console.error('标记废弃失败:', error);
    }
  };

  // 从分析同步
  const handleSync = async () => {
    if (!projectId) return;
    
    setSyncing(true);
    try {
      const result = await foreshadowApi.syncFromAnalysis(projectId, {
        auto_set_planted: true,
      });
      message.success(`同步完成: 新增${result.synced_count}个伏笔, 跳过${result.skipped_count}个`);
      setSyncModalVisible(false);
      loadForeshadows();
    } catch (error) {
      console.error('同步失败:', error);
    } finally {
      setSyncing(false);
    }
  };

  // 打开编辑模态框
  const openEditModal = (foreshadow?: Foreshadow) => {
    setCurrentForeshadow(foreshadow || null);
    if (foreshadow) {
      // 确保数组类型字段不为null
      form.setFieldsValue({
        ...foreshadow,
        tags: foreshadow.tags || [],
        related_characters: foreshadow.related_characters || [],
      });
    } else {
      form.resetFields();
    }
    setEditModalVisible(true);
  };

  // 打开详情模态框
  const openDetailModal = (foreshadow: Foreshadow) => {
    setCurrentForeshadow(foreshadow);
    setDetailModalVisible(true);
  };

  // 打开埋入模态框
  const openPlantModal = (foreshadow: Foreshadow) => {
    setCurrentForeshadow(foreshadow);
    plantForm.resetFields();
    setPlantModalVisible(true);
  };

  // 打开回收模态框
  const openResolveModal = (foreshadow: Foreshadow) => {
    setCurrentForeshadow(foreshadow);
    resolveForm.resetFields();
    setResolveModalVisible(true);
  };

  // 计算紧急程度
  const getUrgencyBadge = (foreshadow: Foreshadow) => {
    if (foreshadow.status !== 'planted' || !foreshadow.target_resolve_chapter_number) {
      return null;
    }
    
    const chaptersWithContent = chapters.filter(c => c.content);
    const currentMaxChapter = chaptersWithContent.length > 0
      ? Math.max(...chaptersWithContent.map(c => c.chapter_number))
      : 0;
    
    const remaining = foreshadow.target_resolve_chapter_number - currentMaxChapter;
    
    if (remaining < 0) {
      return <Badge status="error" text={`已超期${Math.abs(remaining)}章`} />;
    } else if (remaining <= 3) {
      return <Badge status="warning" text={`还剩${remaining}章`} />;
    }
    return null;
  };

  // 状态排序优先级
  const statusOrder: Record<ForeshadowStatus, number> = {
    planted: 1,      // 已埋入优先（需要关注回收）
    pending: 2,      // 待埋入次之
    partially_resolved: 3,
    resolved: 4,
    abandoned: 5,
  };

  // 表格列定义
  const columns = [
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      sorter: (a: Foreshadow, b: Foreshadow) => statusOrder[a.status] - statusOrder[b.status],
      render: (status: ForeshadowStatus) => {
        const config = STATUS_CONFIG[status];
        return (
          <Tag color={config.color} icon={config.icon}>
            {config.label}
          </Tag>
        );
      },
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      sorter: (a: Foreshadow, b: Foreshadow) => a.title.localeCompare(b.title, 'zh-CN'),
      render: (title: string, record: Foreshadow) => (
        <Space direction="vertical" size={0}>
          <Space>
            <a onClick={() => openDetailModal(record)}>{title}</a>
            {record.is_long_term && (
              <Tag color="purple" style={{ marginLeft: 4 }}>长线</Tag>
            )}
          </Space>
          {getUrgencyBadge(record)}
        </Space>
      ),
    },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      width: 80,
      sorter: (a: Foreshadow, b: Foreshadow) => {
        const catA = a.category || '';
        const catB = b.category || '';
        return catA.localeCompare(catB, 'zh-CN');
      },
      render: (category?: ForeshadowCategory) => {
        if (!category) return '-';
        const config = CATEGORY_CONFIG[category];
        return config ? <Tag color={config.color}>{config.label}</Tag> : category;
      },
    },
    {
      title: '埋入章节',
      dataIndex: 'plant_chapter_number',
      key: 'plant_chapter_number',
      width: 120,
      sorter: (a: Foreshadow, b: Foreshadow) => {
        const valA = a.plant_chapter_number ?? 999999;
        const valB = b.plant_chapter_number ?? 999999;
        return valA - valB;
      },
      defaultSortOrder: 'ascend' as const,
      render: (num?: number) => num ? `第${num}章` : '-',
    },
    {
      title: '计划回收',
      dataIndex: 'target_resolve_chapter_number',
      key: 'target_resolve_chapter_number',
      width: 120,
      sorter: (a: Foreshadow, b: Foreshadow) => {
        const valA = a.target_resolve_chapter_number ?? 999999;
        const valB = b.target_resolve_chapter_number ?? 999999;
        return valA - valB;
      },
      render: (num?: number) => num ? `第${num}章` : '-',
    },
    {
      title: '重要性',
      dataIndex: 'importance',
      key: 'importance',
      width: 100,
      sorter: (a: Foreshadow, b: Foreshadow) => a.importance - b.importance,
      render: (importance: number) => {
        const stars = Math.round(importance * 5);
        return '★'.repeat(stars) + '☆'.repeat(5 - stars);
      },
    },
    {
      title: '来源',
      dataIndex: 'source_type',
      key: 'source_type',
      width: 80,
      sorter: (a: Foreshadow, b: Foreshadow) => {
        const srcA = a.source_type || '';
        const srcB = b.source_type || '';
        return srcA.localeCompare(srcB);
      },
      render: (source?: string) => (
        <Tag color={source === 'analysis' ? 'blue' : 'green'}>
          {source === 'analysis' ? '分析' : '手动'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: unknown, record: Foreshadow) => (
        <Space size="small">
          <Tooltip title="查看详情">
            <Button type="text" size="small" icon={<EyeOutlined />} onClick={() => openDetailModal(record)} />
          </Tooltip>
          <Tooltip title="编辑">
            <Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEditModal(record)} />
          </Tooltip>
          {record.status === 'pending' && (
            <Tooltip title="标记埋入">
              <Button type="text" size="small" icon={<FlagOutlined />} onClick={() => openPlantModal(record)} />
            </Tooltip>
          )}
          {record.status === 'planted' && (
            <Tooltip title="标记回收">
              <Button type="text" size="small" icon={<CheckCircleOutlined />} onClick={() => openResolveModal(record)} />
            </Tooltip>
          )}
          {record.status !== 'abandoned' && record.status !== 'resolved' && (
            <Popconfirm
              title="确定要废弃这个伏笔吗？"
              onConfirm={() => handleAbandon(record.id)}
            >
              <Tooltip title="废弃">
                <Button type="text" size="small" danger icon={<CloseCircleOutlined />} />
              </Tooltip>
            </Popconfirm>
          )}
          <Popconfirm
            title="确定要删除这个伏笔吗？"
            onConfirm={() => handleDelete(record.id)}
          >
            <Tooltip title="删除">
              <Button type="text" size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* 统计卡片 */}
      {stats && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={3}>
            <Card size="small">
              <Statistic title="总计" value={stats.total} />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic title="待埋入" value={stats.pending} valueStyle={{ color: token.colorTextSecondary }} />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic title="已埋入" value={stats.planted} valueStyle={{ color: token.colorSuccess }} />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic title="已回收" value={stats.resolved} valueStyle={{ color: token.colorPrimary }} />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic title="长线伏笔" value={stats.long_term_count} valueStyle={{ color: token.colorInfo }} />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic 
                title="超期未回收" 
                value={stats.overdue_count} 
                valueStyle={{ color: stats.overdue_count > 0 ? token.colorError : token.colorTextSecondary }}
                prefix={stats.overdue_count > 0 ? <WarningOutlined /> : null}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* 超期提醒 */}
      {stats && stats.overdue_count > 0 && (
        <Alert
          message={`有 ${stats.overdue_count} 个伏笔已超期未回收`}
          description="请尽快在后续章节中回收这些伏笔，或调整计划回收章节"
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 自动同步提示 */}
      <Alert
        message={
          <Space>
            <InfoCircleOutlined />
            <span>伏笔数据会在章节分析完成后自动同步，无需手动操作</span>
          </Space>
        }
        type="info"
        showIcon={false}
        style={{ marginBottom: 16 }}
        closable
      />

      {/* 工具栏 */}
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          <Select
            placeholder="状态筛选"
            allowClear
            style={{ width: 120 }}
            value={statusFilter}
            onChange={setStatusFilter}
          >
            {Object.entries(STATUS_CONFIG).map(([key, config]) => (
              <Option key={key} value={key}>{config.label}</Option>
            ))}
          </Select>
          <Select
            placeholder="分类筛选"
            allowClear
            style={{ width: 100 }}
            value={categoryFilter}
            onChange={setCategoryFilter}
          >
            {Object.entries(CATEGORY_CONFIG).map(([key, config]) => (
              <Option key={key} value={key}>{config.label}</Option>
            ))}
          </Select>
          <Select
            placeholder="来源筛选"
            allowClear
            style={{ width: 100 }}
            value={sourceFilter}
            onChange={setSourceFilter}
          >
            <Option value="analysis">分析</Option>
            <Option value="manual">手动</Option>
          </Select>
        </Space>
        <Space>
          <Tooltip title="刷新列表">
            <Button
              icon={<ReloadOutlined spin={loading} />}
              onClick={loadForeshadows}
            />
          </Tooltip>
          <Dropdown
            menu={{
              items: [
                {
                  key: 'sync',
                  icon: <SyncOutlined />,
                  label: '手动同步分析伏笔',
                  onClick: () => setSyncModalVisible(true),
                },
              ] as MenuProps['items'],
            }}
            placement="bottomRight"
          >
            <Button icon={<MoreOutlined />}>更多</Button>
          </Dropdown>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => openEditModal()}
          >
            添加伏笔
          </Button>
        </Space>
      </div>

      {/* 伏笔列表 - 表格内容可滚动，表头固定 */}
      <div
        ref={tableContainerRef}
        style={{
          flex: 1,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0, // 重要：让 flex 子元素可以收缩
        }}
      >
        <Table
          dataSource={foreshadows}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={false}
          scroll={{ y: tableScrollY }}
          locale={{
            emptyText: <Empty description="暂无伏笔，点击右上角添加" />,
          }}
        />
      </div>

      {/* 分页器 - 固定在底部居中 */}
      <div style={{
        padding: '12px 0',
        borderTop: `1px solid ${token.colorBorderSecondary}`,
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        flexShrink: 0,
        background: token.colorBgContainer,
      }}>
        <Pagination
          current={currentPage}
          pageSize={pageSize}
          total={total}
          onChange={(page, size) => {
            setCurrentPage(page);
            if (size !== pageSize) {
              setPageSize(size);
            }
          }}
          showSizeChanger
          showTotal={(total) => `共 ${total} 条`}
          showQuickJumper
        />
      </div>

      {/* 创建/编辑模态框 */}
      <Modal
        title={currentForeshadow ? '编辑伏笔' : '添加伏笔'}
        open={editModalVisible}
        centered
        onCancel={() => {
          setEditModalVisible(false);
          setCurrentForeshadow(null);
          form.resetFields();
        }}
        onOk={() => form.submit()}
        width={800}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSave}
          initialValues={{
            importance: 0.5,
            strength: 5,
            subtlety: 5,
            is_long_term: false,
            auto_remind: true,
            remind_before_chapters: 5,
            include_in_context: true,
          }}
        >
          <Row gutter={16}>
            <Col span={16}>
              <Form.Item name="title" label="伏笔标题" rules={[{ required: true, message: '请输入标题' }]}>
                <Input placeholder="简洁描述伏笔内容" maxLength={200} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="category" label="分类">
                <Select placeholder="选择分类" allowClear>
                  {Object.entries(CATEGORY_CONFIG).map(([key, config]) => (
                    <Option key={key} value={key}>{config.label}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>
          
          <Form.Item name="content" label="伏笔内容" rules={[{ required: true, message: '请输入内容' }]}>
            <TextArea rows={3} placeholder="详细描述伏笔的内容和意图" />
          </Form.Item>
          
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item name="plant_chapter_number" label="计划埋入">
                <InputNumber min={1} placeholder="章节号" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="target_resolve_chapter_number" label="计划回收">
                <InputNumber min={1} placeholder="章节号" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="related_characters" label="关联角色">
                <Select
                  mode="multiple"
                  placeholder="选择关联角色"
                  optionFilterProp="children"
                  maxTagCount={3}
                >
                  {characters
                    .filter(char => !char.is_organization)
                    .map(char => (
                      <Option key={char.name} value={char.name}>
                        {char.name} {char.role_type ? `(${char.role_type})` : ''}
                      </Option>
                    ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>
          
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item name="importance" label="重要性 (0-1)">
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="strength" label="强度 (1-10)">
                <InputNumber min={1} max={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="subtlety" label="隐藏度 (1-10)">
                <InputNumber min={1} max={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="is_long_term" label="长线伏笔" valuePropName="checked">
                <Switch checkedChildren="是" unCheckedChildren="否" />
              </Form.Item>
            </Col>
          </Row>
          
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="hint_text" label="暗示文本">
                <TextArea rows={2} placeholder="埋伏笔时使用的暗示性描写" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="notes" label="备注">
                <TextArea rows={2} placeholder="创作备注（仅作者可见）" />
              </Form.Item>
            </Col>
          </Row>
          
          <Divider style={{ margin: '12px 0' }}>AI辅助设置</Divider>
          
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="auto_remind" label="自动提醒" valuePropName="checked" style={{ marginBottom: 0 }}>
                <Switch checkedChildren="开" unCheckedChildren="关" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="include_in_context" label="写作时提醒" valuePropName="checked" style={{ marginBottom: 0 }}>
                <Switch checkedChildren="是" unCheckedChildren="否" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="remind_before_chapters" label="提前几章提醒" style={{ marginBottom: 0 }}>
                <InputNumber min={1} max={20} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 详情模态框 */}
      <Modal
        title="伏笔详情"
        open={detailModalVisible}
        centered
        onCancel={() => {
          setDetailModalVisible(false);
          setCurrentForeshadow(null);
        }}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            关闭
          </Button>,
          <Button key="edit" type="primary" onClick={() => {
            setDetailModalVisible(false);
            openEditModal(currentForeshadow!);
          }}>
            编辑
          </Button>,
        ]}
        width={600}
      >
        {currentForeshadow && (
          <div>
            <Row gutter={[16, 16]}>
              <Col span={24}>
                <h3>{currentForeshadow.title}</h3>
                <Space>
                  <Tag color={STATUS_CONFIG[currentForeshadow.status].color}>
                    {STATUS_CONFIG[currentForeshadow.status].label}
                  </Tag>
                  {currentForeshadow.is_long_term && <Tag color="purple">长线伏笔</Tag>}
                  {currentForeshadow.category && CATEGORY_CONFIG[currentForeshadow.category] && (
                    <Tag color={CATEGORY_CONFIG[currentForeshadow.category].color}>
                      {CATEGORY_CONFIG[currentForeshadow.category].label}
                    </Tag>
                  )}
                </Space>
              </Col>
              
              <Col span={24}>
                <strong>伏笔内容：</strong>
                <p style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>{currentForeshadow.content}</p>
              </Col>
              
              {currentForeshadow.hint_text && (
                <Col span={24}>
                  <strong>暗示文本：</strong>
                  <p style={{ marginTop: 8, whiteSpace: 'pre-wrap', color: token.colorTextSecondary }}>
                    {currentForeshadow.hint_text}
                  </p>
                </Col>
              )}
              
              {currentForeshadow.resolution_text && (
                <Col span={24}>
                  <strong>揭示文本：</strong>
                  <p style={{ marginTop: 8, whiteSpace: 'pre-wrap', color: token.colorTextSecondary }}>
                    {currentForeshadow.resolution_text}
                  </p>
                </Col>
              )}
              
              <Col span={12}>
                <strong>埋入章节：</strong> {currentForeshadow.plant_chapter_number ? `第${currentForeshadow.plant_chapter_number}章` : '未设定'}
              </Col>
              <Col span={12}>
                <strong>计划回收：</strong> {currentForeshadow.target_resolve_chapter_number ? `第${currentForeshadow.target_resolve_chapter_number}章` : '未设定'}
              </Col>
              
              {currentForeshadow.actual_resolve_chapter_number && (
                <Col span={24}>
                  <strong>实际回收：</strong> 第{currentForeshadow.actual_resolve_chapter_number}章
                </Col>
              )}
              
              <Col span={8}>
                <strong>重要性：</strong> {'★'.repeat(Math.round(currentForeshadow.importance * 5))}
              </Col>
              <Col span={8}>
                <strong>强度：</strong> {currentForeshadow.strength}/10
              </Col>
              <Col span={8}>
                <strong>隐藏度：</strong> {currentForeshadow.subtlety}/10
              </Col>
              
              {currentForeshadow.related_characters && currentForeshadow.related_characters.length > 0 && (
                <Col span={24}>
                  <strong>关联角色：</strong>
                  <div style={{ marginTop: 4 }}>
                    {currentForeshadow.related_characters.map((name, idx) => (
                      <Tag key={idx}>{name}</Tag>
                    ))}
                  </div>
                </Col>
              )}
              
              {currentForeshadow.notes && (
                <Col span={24}>
                  <strong>备注：</strong>
                  <p style={{ marginTop: 8, color: token.colorTextSecondary }}>{currentForeshadow.notes}</p>
                </Col>
              )}
              
              <Col span={24}>
                <strong>来源：</strong> {currentForeshadow.source_type === 'analysis' ? '章节分析提取' : '手动添加'}
              </Col>
            </Row>
          </div>
        )}
      </Modal>

      {/* 标记埋入模态框 */}
      <Modal
        title="标记伏笔埋入"
        open={plantModalVisible}
        centered
        onCancel={() => {
          setPlantModalVisible(false);
          setCurrentForeshadow(null);
          plantForm.resetFields();
        }}
        onOk={() => plantForm.submit()}
        destroyOnClose
      >
        <Form form={plantForm} layout="vertical" onFinish={handlePlant}>
          <Form.Item name="chapter_id" label="选择埋入章节" rules={[{ required: true, message: '请选择章节' }]}>
            <Select placeholder="选择章节">
              {chapters.map(chapter => (
                <Option key={chapter.id} value={chapter.id}>
                  第{chapter.chapter_number}章 - {chapter.title}
                </Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="hint_text" label="暗示文本（可选）">
            <TextArea rows={3} placeholder="记录埋伏笔时使用的暗示性描写" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 标记回收模态框 */}
      <Modal
        title="标记伏笔回收"
        open={resolveModalVisible}
        centered
        onCancel={() => {
          setResolveModalVisible(false);
          setCurrentForeshadow(null);
          resolveForm.resetFields();
        }}
        onOk={() => resolveForm.submit()}
        destroyOnClose
      >
        <Form form={resolveForm} layout="vertical" onFinish={handleResolve}>
          <Form.Item name="chapter_id" label="选择回收章节" rules={[{ required: true, message: '请选择章节' }]}>
            <Select placeholder="选择章节">
              {chapters.map(chapter => (
                <Option key={chapter.id} value={chapter.id}>
                  第{chapter.chapter_number}章 - {chapter.title}
                </Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="resolution_text" label="揭示文本（可选）">
            <TextArea rows={3} placeholder="记录回收伏笔时的揭示内容" />
          </Form.Item>
          <Form.Item name="is_partial" label="是否部分回收" valuePropName="checked">
            <Switch checkedChildren="部分" unCheckedChildren="完全" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 同步模态框 */}
      <Modal
        title="手动同步分析伏笔"
        open={syncModalVisible}
        centered
        onCancel={() => setSyncModalVisible(false)}
        onOk={handleSync}
        confirmLoading={syncing}
        okText="开始同步"
      >
        <Alert
          message="提示"
          description="通常情况下，章节分析完成后伏笔会自动同步到伏笔管理中。此功能用于手动补充同步可能遗漏的伏笔。"
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <p>此操作将从已完成的章节分析结果中提取伏笔信息，同步到伏笔管理表。</p>
        <ul>
          <li>已存在的伏笔记录不会被覆盖</li>
          <li>新同步的伏笔将自动设置为"已埋入"状态</li>
          <li>同步完成后可在列表中查看和编辑</li>
        </ul>
      </Modal>
    </div>
  );
}
