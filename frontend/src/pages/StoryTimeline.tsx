import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import {
  Badge,
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
  Slider,
  Space,
  Statistic,
  Switch,
  Tag,
  Timeline,
  Tooltip,
  Typography,
  theme,
} from 'antd';
import {
  ApartmentOutlined,
  BankOutlined,
  BookOutlined,
  BulbOutlined,
  EnvironmentOutlined,
  FieldTimeOutlined,
  FireOutlined,
  FlagOutlined,
  MessageOutlined,
  ReloadOutlined,
  SearchOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { projectApi } from '../services/api';
import type { StoryTimelineChapter, StoryTimelineEvent, StoryTimelineResponse } from '../types';

const { Text, Paragraph, Title } = Typography;

const EVENT_TYPES = [
  { value: 'plot', label: '情节' },
  { value: 'character', label: '角色' },
  { value: 'scene', label: '场景' },
  { value: 'world', label: '世界观' },
  { value: 'foreshadow', label: '伏笔' },
  { value: 'organization', label: '组织' },
  { value: 'hook', label: '钩子' },
  { value: 'dialogue', label: '对话' },
];

const TYPE_META: Record<string, { label: string; color: string; icon: ReactNode }> = {
  plot: { label: '情节', color: 'blue', icon: <FlagOutlined /> },
  character: { label: '角色', color: 'purple', icon: <UserOutlined /> },
  scene: { label: '场景', color: 'cyan', icon: <EnvironmentOutlined /> },
  world: { label: '世界观', color: 'green', icon: <BookOutlined /> },
  foreshadow: { label: '伏笔', color: 'gold', icon: <BulbOutlined /> },
  organization: { label: '组织', color: 'magenta', icon: <BankOutlined /> },
  hook: { label: '钩子', color: 'volcano', icon: <FireOutlined /> },
  dialogue: { label: '对话', color: 'geekblue', icon: <MessageOutlined /> },
  other: { label: '事实', color: 'default', icon: <ApartmentOutlined /> },
};

type TimelineQueryParams = {
  types?: string;
  search?: string;
  min_importance?: number;
  limit?: number;
};

function eventMeta(type: string) {
  return TYPE_META[type] || TYPE_META.other;
}

function sourceLabel(sourceType: string) {
  if (sourceType === 'story_memory') return '章节记忆';
  if (sourceType === 'plot_analysis') return '剧情分析';
  if (sourceType === 'foreshadow') return '伏笔管理';
  return sourceType;
}

function statusLabel(status?: string | null) {
  const map: Record<string, string> = {
    planted: '已埋入',
    target: '计划',
    resolved: '已回收',
    pending: '待处理',
    partially_resolved: '部分回收',
    abandoned: '已废弃',
  };
  return status ? map[status] || status : '';
}

export default function StoryTimeline() {
  const { projectId } = useParams<{ projectId: string }>();
  const [timeline, setTimeline] = useState<StoryTimelineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [minImportance, setMinImportance] = useState(0);
  const [showEmptyChapters, setShowEmptyChapters] = useState(false);
  const { token } = theme.useToken();

  const timelineQueryParams = useMemo<TimelineQueryParams>(() => ({
    types: selectedTypes.length > 0 ? selectedTypes.join(',') : undefined,
    search: search.trim() || undefined,
    min_importance: minImportance > 0 ? minImportance : undefined,
    limit: 3000,
  }), [selectedTypes, search, minImportance]);

  const loadTimeline = useCallback(async (params: TimelineQueryParams = timelineQueryParams) => {
    if (!projectId) return;
    setLoading(true);
    try {
      const data = await projectApi.getStoryTimeline(projectId, params);
      setTimeline(data);
    } catch (error) {
      console.error('加载时间线失败:', error);
    } finally {
      setLoading(false);
    }
  }, [projectId, timelineQueryParams]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      loadTimeline(timelineQueryParams);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [loadTimeline, timelineQueryParams]);

  const filtered = useMemo(() => {
    if (!timeline) {
      return {
        chapters: [] as StoryTimelineChapter[],
        unplacedEvents: [] as StoryTimelineEvent[],
        totalEvents: 0,
        analyzedChapters: 0,
      };
    }

    const keyword = search.trim().toLowerCase();
    const typeSet = new Set(selectedTypes);

    const matchEvent = (event: StoryTimelineEvent) => {
      if (typeSet.size > 0 && !typeSet.has(event.event_type)) return false;
      if ((event.importance || 0) < minImportance) return false;
      if (!keyword) return true;
      const text = [
        event.title,
        event.content,
        ...(event.tags || []),
        ...(event.entities || []),
        ...(event.locations || []),
      ].join(' ').toLowerCase();
      return text.includes(keyword);
    };

    const chapters = timeline.chapters
      .map((chapter) => ({
        ...chapter,
        events: chapter.events.filter(matchEvent),
      }))
      .filter((chapter) => showEmptyChapters || chapter.events.length > 0);

    const unplacedEvents = timeline.unplaced_events.filter(matchEvent);
    const totalEvents = chapters.reduce((sum, chapter) => sum + chapter.events.length, 0) + unplacedEvents.length;

    return {
      chapters,
      unplacedEvents,
      totalEvents,
      analyzedChapters: chapters.filter((chapter) => chapter.has_analysis).length,
    };
  }, [timeline, selectedTypes, search, minImportance, showEmptyChapters]);

  const scrollToChapter = (chapterNumber: number) => {
    document.getElementById(`timeline-chapter-${chapterNumber}`)?.scrollIntoView({
      block: 'start',
      behavior: 'smooth',
    });
  };

  const renderEvent = (event: StoryTimelineEvent) => {
    const meta = eventMeta(event.event_type);
    return (
      <List.Item key={event.id} style={{ padding: '10px 0' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '96px minmax(0, 1fr)',
          gap: 10,
          width: '100%',
        }}>
          <Tag color={meta.color} icon={meta.icon} style={{ width: 'fit-content', marginTop: 2 }}>
            {event.label || meta.label}
          </Tag>
          <Space direction="vertical" size={4} style={{ minWidth: 0 }}>
            <Space size={[6, 6]} wrap>
              <Text strong>{event.title}</Text>
              {statusLabel(event.status) && <Tag>{statusLabel(event.status)}</Tag>}
              <Tag color="default">{sourceLabel(event.source_type)}</Tag>
              {event.importance >= 0.75 && <Tag color="red">重点</Tag>}
            </Space>
            <Paragraph
              style={{ margin: 0, color: token.colorTextSecondary }}
              ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
            >
              {event.content}
            </Paragraph>
            {(event.entities.length > 0 || event.locations.length > 0 || event.tags.length > 0) && (
              <Space size={[4, 4]} wrap>
                {event.entities.slice(0, 6).map((name) => (
                  <Tag key={`entity-${event.id}-${name}`} color="purple">{name}</Tag>
                ))}
                {event.locations.slice(0, 4).map((location) => (
                  <Tag key={`location-${event.id}-${location}`} color="cyan">{location}</Tag>
                ))}
                {event.tags.slice(0, 5).map((tag) => (
                  <Tag key={`tag-${event.id}-${tag}`}>{tag}</Tag>
                ))}
              </Space>
            )}
          </Space>
        </div>
      </List.Item>
    );
  };

  const renderChapter = (chapter: StoryTimelineChapter) => {
    const score = chapter.coherence_score;
    const timelineColor = chapter.events.length > 0
      ? token.colorPrimary
      : token.colorTextQuaternary;

    return {
      key: chapter.id,
      color: timelineColor,
      children: (
        <div
          id={`timeline-chapter-${chapter.chapter_number}`}
          style={{
            scrollMarginTop: 16,
            border: `1px solid ${token.colorBorderSecondary}`,
            borderRadius: 8,
            background: token.colorBgContainer,
            padding: 14,
          }}
        >
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Space align="start" style={{ justifyContent: 'space-between', width: '100%' }} wrap>
              <Space direction="vertical" size={2}>
                <Space size={[8, 6]} wrap>
                  <Badge count={`第${chapter.chapter_number}章`} color={token.colorPrimary} />
                  <Title level={5} style={{ margin: 0 }}>{chapter.title}</Title>
                </Space>
                <Space size={[6, 6]} wrap>
                  <Tag>{chapter.word_count || 0}字</Tag>
                  {chapter.has_analysis ? <Tag color="green">已分析</Tag> : <Tag>未分析</Tag>}
                  {chapter.plot_stage && <Tag color="blue">{chapter.plot_stage}</Tag>}
                  {chapter.emotional_tone && <Tag color="magenta">{chapter.emotional_tone}</Tag>}
                  {chapter.conflict_level != null && <Tag color="volcano">冲突 {chapter.conflict_level}/10</Tag>}
                </Space>
              </Space>
              {score != null && (
                <Tooltip title="连贯性评分">
                  <Progress
                    type="circle"
                    size={48}
                    percent={Math.round(score * 10)}
                    format={() => score.toFixed(1)}
                    strokeColor={score >= 7 ? token.colorSuccess : score >= 5 ? token.colorWarning : token.colorError}
                  />
                </Tooltip>
              )}
            </Space>

            {chapter.summary && (
              <Text type="secondary">{chapter.summary}</Text>
            )}

            {chapter.events.length > 0 ? (
              <List
                size="small"
                dataSource={chapter.events}
                renderItem={renderEvent}
                split
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本章暂无时间线事件" />
            )}
          </Space>
        </div>
      ),
    };
  };

  if (loading && !timeline) {
    return <Skeleton active paragraph={{ rows: 12 }} />;
  }

  return (
    <div style={{ height: '100%', overflow: 'auto', paddingRight: 4 }}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Space align="center" style={{ justifyContent: 'space-between', width: '100%' }}>
          <Space align="center">
            <FieldTimeOutlined style={{ fontSize: 24, color: token.colorPrimary }} />
            <Title level={3} style={{ margin: 0 }}>时间线</Title>
          </Space>
          <Tooltip title="刷新">
            <Button icon={<ReloadOutlined />} onClick={() => loadTimeline(timelineQueryParams)} loading={loading} />
          </Tooltip>
        </Space>

        <Row gutter={[12, 12]}>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic title="章节" value={timeline?.total_chapters || 0} />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic title="已分析" value={timeline?.analyzed_chapters || 0} suffix={`/ ${timeline?.total_chapters || 0}`} />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic title="事件" value={filtered.totalEvents} />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic title="伏笔" value={timeline?.event_counts?.foreshadow || 0} />
            </Card>
          </Col>
        </Row>

        <Card size="small" bodyStyle={{ padding: 12 }}>
          <Row gutter={[12, 12]} align="middle">
            <Col xs={24} lg={7}>
              <Input
                allowClear
                prefix={<SearchOutlined />}
                placeholder="搜索标题、内容、角色、地点"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </Col>
            <Col xs={24} lg={8}>
              <Select
                mode="multiple"
                allowClear
                placeholder="事件类型"
                value={selectedTypes}
                onChange={setSelectedTypes}
                options={EVENT_TYPES}
                style={{ width: '100%' }}
                maxTagCount="responsive"
              />
            </Col>
            <Col xs={24} md={12} lg={5}>
              <Space direction="vertical" size={0} style={{ width: '100%' }}>
                <Text type="secondary">重要性 {minImportance.toFixed(1)}</Text>
                <Slider
                  min={0}
                  max={1}
                  step={0.1}
                  value={minImportance}
                  onChange={setMinImportance}
                  tooltip={{ formatter: (value) => value?.toFixed(1) }}
                />
              </Space>
            </Col>
            <Col xs={24} md={12} lg={4}>
              <Space>
                <Switch checked={showEmptyChapters} onChange={setShowEmptyChapters} />
                <Text>空章节</Text>
              </Space>
            </Col>
          </Row>
        </Card>

        {!timeline || (filtered.chapters.length === 0 && filtered.unplacedEvents.length === 0) ? (
          <Empty description="暂无符合条件的时间线事件" />
        ) : (
          <Row gutter={[16, 16]} align="top">
            <Col xs={24} xl={6}>
              <div style={{
                position: 'sticky',
                top: 0,
                border: `1px solid ${token.colorBorderSecondary}`,
                borderRadius: 8,
                background: token.colorBgContainer,
                maxHeight: 560,
                overflow: 'auto',
              }}>
                <List
                  size="small"
                  dataSource={filtered.chapters}
                  renderItem={(chapter) => (
                    <List.Item
                      key={chapter.id}
                      onClick={() => scrollToChapter(chapter.chapter_number)}
                      style={{
                        cursor: 'pointer',
                        padding: '10px 12px',
                      }}
                    >
                      <Space direction="vertical" size={2} style={{ width: '100%' }}>
                        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                          <Text strong>第{chapter.chapter_number}章</Text>
                          <Badge count={chapter.events.length} style={{ backgroundColor: token.colorPrimary }} />
                        </Space>
                        <Text ellipsis style={{ maxWidth: '100%' }}>{chapter.title}</Text>
                      </Space>
                    </List.Item>
                  )}
                />
              </div>
            </Col>
            <Col xs={24} xl={18}>
              <Timeline items={filtered.chapters.map(renderChapter)} />
              {filtered.unplacedEvents.length > 0 && (
                <div style={{
                  border: `1px solid ${token.colorBorderSecondary}`,
                  borderRadius: 8,
                  background: token.colorBgContainer,
                  padding: 14,
                  marginLeft: 26,
                }}>
                  <Space direction="vertical" size={8} style={{ width: '100%' }}>
                    <Title level={5} style={{ margin: 0 }}>未定位事件</Title>
                    <List
                      size="small"
                      dataSource={filtered.unplacedEvents}
                      renderItem={renderEvent}
                    />
                  </Space>
                </div>
              )}
            </Col>
          </Row>
        )}
      </Space>
    </div>
  );
}
