import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  List,
  Progress,
  Row,
  Select,
  Skeleton,
  Space,
  Tag,
  Timeline,
  Tooltip,
  Typography,
  message,
  theme,
} from 'antd';
import {
  CheckCircleOutlined,
  ClusterOutlined,
  CopyOutlined,
  ExclamationCircleOutlined,
  FieldTimeOutlined,
  ProfileOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { projectApi } from '../services/api';
import type {
  StoryEngineBeat,
  StoryEngineCardDraft,
  StoryEngineLane,
  StoryEngineMetric,
  StoryEngineRecommendation,
  StoryEngineSection,
  StoryEngineSnapshot,
  StoryEngineTimelineItem,
  StoryEngineVisualization,
} from '../types';

const { Text, Title, Paragraph } = Typography;

const STATUS_META: Record<string, { color: string; label: string }> = {
  ok: { color: 'success', label: '就绪' },
  warning: { color: 'warning', label: '待补强' },
  empty: { color: 'default', label: '空' },
  neutral: { color: 'processing', label: '参考' },
};

const PRIORITY_META: Record<string, { color: string; label: string }> = {
  high: { color: 'red', label: '高' },
  medium: { color: 'orange', label: '中' },
  low: { color: 'blue', label: '低' },
};

function metricDisplay(metric: StoryEngineMetric) {
  if (typeof metric.total === 'number') {
    return `${metric.value}/${metric.total}`;
  }
  return String(metric.value);
}

function statusMeta(status: string) {
  return STATUS_META[status] || STATUS_META.neutral;
}

function priorityMeta(priority: string) {
  return PRIORITY_META[priority] || PRIORITY_META.medium;
}

export default function StoryEngine() {
  const { projectId } = useParams<{ projectId: string }>();
  const [snapshot, setSnapshot] = useState<StoryEngineSnapshot | null>(null);
  const [visualization, setVisualization] = useState<StoryEngineVisualization | null>(null);
  const [loading, setLoading] = useState(false);
  const [visualQuery, setVisualQuery] = useState('');
  const [timelineFilter, setTimelineFilter] = useState<string>('all');
  const { token } = theme.useToken();

  const loadSnapshot = useCallback(async () => {
    if (!projectId) return;

    setLoading(true);
    try {
      const [data, visualData] = await Promise.all([
        projectApi.getStoryEngineSnapshot(projectId),
        projectApi.getStoryEngineVisualization(projectId),
      ]);
      setSnapshot(data);
      setVisualization(visualData);
    } catch (error) {
      console.error('加载剧情工程快照失败:', error);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadSnapshot();
  }, [loadSnapshot]);

  const contextPreview = useMemo(() => {
    if (!snapshot?.context_text) return '';
    return snapshot.context_text.length > 3600
      ? `${snapshot.context_text.slice(0, 3600).trim()}...`
      : snapshot.context_text;
  }, [snapshot?.context_text]);

  const copyContext = async () => {
    if (!snapshot?.context_text) return;
    try {
      await navigator.clipboard.writeText(snapshot.context_text);
      message.success('上下文已复制');
    } catch (error) {
      console.error('复制剧情工程上下文失败:', error);
      message.error('复制失败');
    }
  };

  const renderMetric = (metric: StoryEngineMetric) => {
    const meta = statusMeta(metric.status);
    return (
      <Col xs={12} sm={8} lg={6} key={metric.key}>
        <Card
          size="small"
          styles={{ body: { padding: '14px 16px' } }}
          style={{ height: '100%' }}
        >
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            <Space style={{ justifyContent: 'space-between', width: '100%' }}>
              <Text type="secondary">{metric.label}</Text>
              <Tag color={meta.color}>{meta.label}</Tag>
            </Space>
            <Text strong style={{ fontSize: 22 }}>{metricDisplay(metric)}</Text>
            {metric.description && (
              <Text type="secondary" style={{ fontSize: 12 }}>{metric.description}</Text>
            )}
          </Space>
        </Card>
      </Col>
    );
  };

  const renderSection = (section: StoryEngineSection) => {
    const meta = statusMeta(section.status);
    return (
      <Col xs={24} lg={12} key={section.key}>
        <Card
          title={
            <Space>
              <span>{section.title}</span>
              <Tag color={meta.color}>{section.total}</Tag>
            </Space>
          }
          extra={<Progress percent={section.coverage} size="small" style={{ width: 96 }} />}
          style={{ height: '100%' }}
          styles={{ body: { paddingTop: 12 } }}
        >
          {section.description && (
            <Paragraph type="secondary" style={{ marginBottom: 12 }}>
              {section.description}
            </Paragraph>
          )}
          {section.items.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无资料" />
          ) : (
            <List
              size="small"
              dataSource={section.items}
              renderItem={(item) => (
                <List.Item style={{ paddingInline: 0 }}>
                  <List.Item.Meta
                    title={
                      <Space wrap size={6}>
                        <Text strong>{item.title}</Text>
                        {item.subtitle && <Text type="secondary">{item.subtitle}</Text>}
                        {item.tags.map((tag) => (
                          <Tag key={`${item.id}:${tag}`}>{tag}</Tag>
                        ))}
                      </Space>
                    }
                    description={item.summary || '暂无摘要'}
                  />
                </List.Item>
              )}
            />
          )}
        </Card>
      </Col>
    );
  };

  const renderLane = (lane: StoryEngineLane) => {
    const meta = statusMeta(lane.status);
    return (
      <Col xs={24} xl={12} key={lane.key}>
        <Card
          title={
            <Space wrap>
              <Text strong>{lane.title}</Text>
              <Tag color={meta.color}>{meta.label}</Tag>
              {lane.tags.map((tag) => (
                <Tag key={`${lane.key}:${tag}`}>{tag}</Tag>
              ))}
            </Space>
          }
          extra={<Progress percent={lane.progress} size="small" style={{ width: 108 }} />}
          style={{ height: '100%' }}
          styles={{ body: { paddingTop: 12 } }}
        >
          <Paragraph type="secondary" style={{ marginBottom: 12 }}>
            {lane.summary}
          </Paragraph>
          {lane.items.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可派生线索" />
          ) : (
            <List
              size="small"
              dataSource={lane.items.slice(0, 6)}
              renderItem={(item) => (
                <List.Item style={{ paddingInline: 0 }}>
                  <List.Item.Meta
                    title={
                      <Space wrap size={6}>
                        <Text>{item.title}</Text>
                        {item.subtitle && <Text type="secondary">{item.subtitle}</Text>}
                        {item.tags.map((tag) => (
                          <Tag key={`${lane.key}:${item.id}:${tag}`}>{tag}</Tag>
                        ))}
                      </Space>
                    }
                    description={item.summary || '暂无摘要'}
                  />
                </List.Item>
              )}
            />
          )}
        </Card>
      </Col>
    );
  };

  const renderBeat = (beat: StoryEngineBeat) => {
    const meta = statusMeta(beat.status);
    return (
      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        <Space wrap size={6}>
          <Text strong>{beat.title}</Text>
          <Tag color={meta.color}>{meta.label}</Tag>
          {typeof beat.conflict_level === 'number' && (
            <Tag color={beat.conflict_level >= 7 ? 'red' : 'orange'}>冲突 {beat.conflict_level}</Tag>
          )}
          {beat.stage && <Tag>{beat.stage}</Tag>}
          {beat.emotional_tone && <Tag>{beat.emotional_tone}</Tag>}
          {beat.tags.map((tag) => (
            <Tag key={`${beat.id}:${tag}`}>{tag}</Tag>
          ))}
        </Space>
        <Progress percent={beat.progress} size="small" style={{ maxWidth: 220 }} />
        <Text type="secondary">{beat.summary || '暂无节拍摘要'}</Text>
      </Space>
    );
  };

  const renderCardDraft = (card: StoryEngineCardDraft) => (
    <List.Item style={{ paddingInline: 0 }}>
      <List.Item.Meta
        avatar={<ProfileOutlined style={{ color: token.colorPrimary }} />}
        title={
          <Space wrap size={6}>
            <Text strong>{card.title}</Text>
            <Tag color="processing">{card.card_type}</Tag>
            {card.chapter_number && <Tag>第{card.chapter_number}章</Tag>}
            {card.source_title && <Text type="secondary">{card.source_title}</Text>}
            {card.tags.map((tag) => (
              <Tag key={`${card.id}:${tag}`}>{tag}</Tag>
            ))}
          </Space>
        }
        description={card.content}
      />
    </List.Item>
  );

  const renderRecommendation = (item: StoryEngineRecommendation) => {
    const meta = priorityMeta(item.priority);
    const sourcePathMap: Record<string, string> = {
      'world-setting': 'world-setting',
      outline: 'outline',
      characters: 'characters',
      relationships: 'relationships',
      careers: 'careers',
      organizations: 'organizations',
      'chapter-analysis': 'chapter-analysis',
      foreshadows: 'foreshadows',
    };
    const sourcePath = sourcePathMap[item.source];

    return (
      <List.Item style={{ paddingInline: 0 }}>
        <List.Item.Meta
          avatar={<ExclamationCircleOutlined style={{ color: token.colorWarning }} />}
          title={
            <Space wrap>
              <Text strong>{item.title}</Text>
              <Tag color={meta.color}>{meta.label}</Tag>
            </Space>
          }
          description={item.detail}
        />
        {sourcePath && projectId && (
          <Button type="link" size="small">
            <Link to={`/project/${projectId}/${sourcePath}`}>打开</Link>
          </Button>
        )}
      </List.Item>
    );
  };

  const renderTimelineItem = (item: StoryEngineTimelineItem) => (
    <Space direction="vertical" size={2} style={{ width: '100%' }}>
      <Space wrap size={6}>
        <Text strong>{item.title}</Text>
        {item.chapter_number && <Tag>第{item.chapter_number}章</Tag>}
        {item.entities.slice(0, 3).map((entity) => (
          <Tag key={`${item.id}:${entity}`} color="blue">{entity}</Tag>
        ))}
        {item.tags.slice(0, 3).map((tag) => (
          <Tag key={`${item.id}:${tag}`}>{tag}</Tag>
        ))}
      </Space>
      <Text type="secondary">{item.content}</Text>
    </Space>
  );

  const renderVisualization = () => {
    if (!visualization) return null;
    const normalizedQuery = visualQuery.trim().toLowerCase();
    const matchText = (...values: unknown[]) => {
      if (!normalizedQuery) return true;
      return values
        .flatMap((value) => Array.isArray(value) ? value : [value])
        .some((value) => String(value || '').toLowerCase().includes(normalizedQuery));
    };
    const matrixRows = visualization.character_chapter_matrix.filter((row) =>
      matchText(row.entity, row.chapters.map((cell) => cell.evidence || ''))
    );
    const timelineGroups = [
      { key: 'relationship', title: '关系变化时间线', items: visualization.relationship_timeline },
      { key: 'foreshadow', title: '伏笔时间线', items: visualization.foreshadow_timeline },
      { key: 'organization', title: '组织变化时间线', items: visualization.organization_timeline },
      { key: 'world', title: '世界观声明时间线', items: visualization.world_timeline },
    ]
      .filter((group) => timelineFilter === 'all' || group.key === timelineFilter)
      .map((group) => ({
        ...group,
        items: group.items.filter((item) =>
          matchText(item.title, item.content, item.entities, item.tags, item.chapter_number)
        ),
      }))
      .filter((group) => group.items.length > 0);

    if (!matrixRows.length && !timelineGroups.length) {
      return null;
    }

    return (
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space align="center" style={{ justifyContent: 'space-between', width: '100%' }}>
          <Title level={4} style={{ margin: 0 }}>剧情图谱</Title>
          <Text type="secondary">由结构化事实派生</Text>
        </Space>
        <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
          <Input.Search
            allowClear
            placeholder="搜索角色、章节证据、关系、伏笔或世界观事实"
            value={visualQuery}
            onChange={(event) => setVisualQuery(event.target.value)}
            style={{ width: 360, maxWidth: '100%' }}
          />
          <Select
            value={timelineFilter}
            onChange={setTimelineFilter}
            style={{ width: 180 }}
            options={[
              { label: '全部时间线', value: 'all' },
              { label: '关系变化', value: 'relationship' },
              { label: '伏笔', value: 'foreshadow' },
              { label: '组织变化', value: 'organization' },
              { label: '世界观声明', value: 'world' },
            ]}
          />
        </Space>
        <Row gutter={[12, 12]}>
          {matrixRows.length > 0 && (
            <Col xs={24} xl={12}>
              <Card size="small" title="角色-章节出现矩阵" style={{ height: '100%' }}>
                <List
                  size="small"
                  dataSource={matrixRows.slice(0, 12)}
                  renderItem={(row) => (
                    <List.Item style={{ paddingInline: 0 }}>
                      <Space direction="vertical" size={4} style={{ width: '100%' }}>
                        <Space wrap>
                          <Text strong>{row.entity}</Text>
                          <Tag color="processing">{row.total} 条事实</Tag>
                        </Space>
                        <Space size={[4, 4]} wrap>
                          {row.chapters.slice(0, 18).map((cell) => (
                            <Tooltip
                              key={`${row.entity}:${cell.chapter_number}`}
                              title={cell.evidence || `${cell.count} 条事实`}
                            >
                              <Tag color={cell.count >= 3 ? 'green' : 'default'}>
                                {cell.chapter_number}:{cell.count}
                              </Tag>
                            </Tooltip>
                          ))}
                        </Space>
                      </Space>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
          )}
          {timelineGroups.slice(0, 2).map((group) => (
            <Col xs={24} xl={12} key={group.key}>
              <Card size="small" title={group.title} style={{ height: '100%' }}>
                <Timeline
                  items={group.items.slice(0, 10).map((item) => ({
                    key: item.id,
                    color: item.timeline_type === 'foreshadow' ? token.colorWarning : token.colorPrimary,
                    children: renderTimelineItem(item),
                  }))}
                />
              </Card>
            </Col>
          ))}
          {timelineGroups.slice(2).map((group) => (
            <Col xs={24} xl={12} key={group.key}>
              <Card size="small" title={group.title} style={{ height: '100%' }}>
                <Timeline
                  items={group.items.slice(0, 10).map((item) => ({
                    key: item.id,
                    color: group.key === 'world' ? token.colorSuccess : token.colorPrimary,
                    children: renderTimelineItem(item),
                  }))}
                />
              </Card>
            </Col>
          ))}
        </Row>
      </Space>
    );
  };

  if (loading && !snapshot) {
    return <Skeleton active paragraph={{ rows: 10 }} />;
  }

  return (
    <div style={{ height: '100%', overflow: 'auto', paddingRight: 4 }}>
      <Space direction="vertical" size={18} style={{ width: '100%' }}>
        <Space align="center" style={{ justifyContent: 'space-between', width: '100%' }}>
          <Space align="center">
            <ClusterOutlined style={{ fontSize: 24, color: token.colorPrimary }} />
            <Title level={3} style={{ margin: 0 }}>剧情工程</Title>
          </Space>
          <Space>
            <Tooltip title="刷新快照">
              <Button icon={<ReloadOutlined />} onClick={loadSnapshot} loading={loading} />
            </Tooltip>
            <Tooltip title="复制 AI 上下文">
              <Button icon={<CopyOutlined />} onClick={copyContext} disabled={!snapshot?.context_text} />
            </Tooltip>
          </Space>
        </Space>

        {snapshot ? (
          <>
            <Alert
              type={snapshot.readiness_score >= 70 ? 'success' : snapshot.readiness_score >= 40 ? 'warning' : 'info'}
              showIcon
              icon={snapshot.readiness_score >= 70 ? <CheckCircleOutlined /> : undefined}
              message={
                <Space wrap>
                  <Text strong>工程化就绪度</Text>
                  <Progress
                    percent={snapshot.readiness_score}
                    size="small"
                    style={{ width: 160 }}
                    strokeColor={snapshot.readiness_score >= 70 ? token.colorSuccess : token.colorWarning}
                  />
                  <Text>{snapshot.readiness_score}%</Text>
                </Space>
              }
            />

            <Row gutter={[12, 12]}>
              {snapshot.metrics.map(renderMetric)}
            </Row>

            {snapshot.recommendations.length > 0 && (
              <Card title="下一步">
                <List
                  size="small"
                  dataSource={snapshot.recommendations}
                  renderItem={renderRecommendation}
                />
              </Card>
            )}

            {(snapshot.lanes || []).length > 0 && (
              <Card
                title="剧情线索"
                extra={<Text type="secondary">由现有官方数据派生，不新增专用表</Text>}
              >
                <Row gutter={[12, 12]}>
                  {snapshot.lanes.map(renderLane)}
                </Row>
              </Card>
            )}

            {renderVisualization()}

            {((snapshot.beats || []).length > 0 || (snapshot.cards || []).length > 0) && (
              <Row gutter={[12, 12]}>
                {(snapshot.beats || []).length > 0 && (
                  <Col xs={24} xl={12}>
                    <Card
                      title={
                        <Space>
                          <FieldTimeOutlined />
                          <span>时间线节拍</span>
                        </Space>
                      }
                      extra={<Text type="secondary">最多展示前 16 个节点</Text>}
                      style={{ height: '100%' }}
                    >
                      <Timeline
                        items={(snapshot.beats || []).slice(0, 16).map((beat) => ({
                          key: beat.id,
                          color: beat.status === 'warning'
                            ? token.colorWarning
                            : beat.status === 'ok'
                              ? token.colorSuccess
                              : token.colorPrimary,
                          children: renderBeat(beat),
                        }))}
                      />
                    </Card>
                  </Col>
                )}
                {(snapshot.cards || []).length > 0 && (
                  <Col xs={24} xl={12}>
                    <Card
                      title={
                        <Space>
                          <ProfileOutlined />
                          <span>剧情卡草稿</span>
                        </Space>
                      }
                      extra={<Text type="secondary">由分析结果优先派生</Text>}
                      style={{ height: '100%' }}
                    >
                      <List
                        size="small"
                        dataSource={(snapshot.cards || []).slice(0, 12)}
                        renderItem={renderCardDraft}
                      />
                    </Card>
                  </Col>
                )}
              </Row>
            )}

            <Row gutter={[12, 12]}>
              {snapshot.sections.map(renderSection)}
            </Row>

            <Card
              title="AI 上下文快照"
              extra={<Button size="small" icon={<CopyOutlined />} onClick={copyContext}>复制</Button>}
            >
              <pre style={{
                margin: 0,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                maxHeight: 460,
                overflow: 'auto',
                color: token.colorTextSecondary,
                background: token.colorFillQuaternary,
                border: `1px solid ${token.colorBorderSecondary}`,
                borderRadius: 8,
                padding: 12,
                fontSize: 13,
                lineHeight: 1.7,
              }}>
                {contextPreview || '暂无可用上下文'}
              </pre>
            </Card>
          </>
        ) : (
          <Empty description="暂无剧情工程快照" />
        )}
      </Space>
    </div>
  );
}
