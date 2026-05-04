import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Card, List, Button, Space, Badge, Tag, Progress, Popconfirm, Empty, theme, Tooltip, message } from 'antd';
import {
  ClockCircleOutlined,
  LoadingOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  DeleteOutlined,
  UpOutlined,
  DownOutlined,
  ClearOutlined,
} from '@ant-design/icons';
import { getProjectTasks, cancelTask, cancelBatchTask, deleteTask, clearProjectTasks, type TaskStatus } from '../services/backgroundTaskService';
import { eventBus } from '../store/eventBus';

interface FloatingTaskPanelProps {
  projectId: string;
  autoRefreshInterval?: number; // 自动刷新间隔（毫秒），默认3000
}

/**
 * 悬浮任务框组件
 * 显示在页面右下角，支持收起/展开
 */
export const FloatingTaskPanel: React.FC<FloatingTaskPanelProps> = ({
  projectId,
  autoRefreshInterval = 3000,
}) => {
  const [taskList, setTaskList] = useState<TaskStatus[]>([]);
  const [loading, setLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(true); // 默认收起
  const userCollapsedRef = useRef(false); // 用户手动收起标记
  const { token } = theme.useToken();

  // 加载任务列表
  const loadTasks = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const result = await getProjectTasks(projectId);
      setTaskList(result.items || []);
    } catch (error) {
      console.error('加载任务列表失败:', error);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  // 初始加载
  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  // 监听后台任务创建事件，立即刷新列表并展开浮窗
  useEffect(() => {
    const handleTaskCreated = () => {
      loadTasks();
      // 创建新任务时自动展开（重置用户手动收起标记）
      userCollapsedRef.current = false;
      setCollapsed(false);
    };
    eventBus.on('background-task-created', handleTaskCreated);
    return () => {
      eventBus.off('background-task-created', handleTaskCreated);
    };
  }, [loadTasks]);

  // 有活跃任务时自动展开（仅当用户没有手动收起时）
  useEffect(() => {
    const hasActiveTasks = taskList.some(
      (t) => t.status === 'running' || t.status === 'pending'
    );
    if (hasActiveTasks && !userCollapsedRef.current) {
      setCollapsed(false);
    }
  }, [taskList]);

  // 自动刷新（仅当有运行中或等待中的任务时）
  useEffect(() => {
    const hasActiveTasks = taskList.some(
      (t) => t.status === 'running' || t.status === 'pending'
    );
    
    if (!hasActiveTasks) return;

    const timer = setInterval(loadTasks, autoRefreshInterval);
    return () => clearInterval(timer);
  }, [taskList, autoRefreshInterval, loadTasks]);

  // 取消任务
  const handleCancelTask = async (task: TaskStatus) => {
    try {
      if (task.task_type === 'chapter_batch') {
        await cancelBatchTask(task.id);
      } else {
        await cancelTask(task.id);
      }
      loadTasks();
    } catch (error) {
      console.error('取消任务失败:', error);
    }
  };

  // 删除任务记录
  const handleDeleteTask = async (taskId: string) => {
    try {
      await deleteTask(taskId);
      loadTasks();
    } catch (error) {
      console.error('删除任务记录失败:', error);
    }
  };

  // 一键清理已结束的任务记录
  const handleClearTasks = async () => {
    try {
      const result = await clearProjectTasks(projectId);
      message.success(`已清理 ${result.deleted_count} 条任务记录`);
      loadTasks();
    } catch (error) {
      console.error('清理任务记录失败:', error);
      message.error('清理任务记录失败');
    }
  };

  // 获取任务状态标签
  const getTaskStatusTag = (status: TaskStatus['status']) => {
    switch (status) {
      case 'pending':
        return <Tag icon={<ClockCircleOutlined />} color="default">等待中</Tag>;
      case 'running':
        return <Tag icon={<LoadingOutlined />} color="processing">运行中</Tag>;
      case 'completed':
        return <Tag icon={<CheckCircleOutlined />} color="success">已完成</Tag>;
      case 'failed':
        return <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>;
      case 'cancelled':
        return <Tag icon={<CloseCircleOutlined />} color="default">已取消</Tag>;
      default:
        return <Tag>{status}</Tag>;
    }
  };

  // 获取任务类型标签
  const getTaskTypeLabel = (taskType: string) => {
    switch (taskType) {
      case 'outline_new':
        return '大纲生成';
      case 'outline_continue':
        return '大纲续写';
      case 'outline_expand':
        return '大纲展开';
      case 'outline_batch_expand':
        return '批量大纲展开';
      case 'outline_optimize':
        return '大纲优化';
      case 'character_optimize':
        return '角色设定优化';
      case 'chapter_generate':
        return '章节生成';
      case 'chapter_batch':
        return '批量章节生成';
      case 'wizard':
        return '向导创建';
      case 'book_import_parse':
        return '拆书解析';
      default:
        return taskType;
    }
  };

  const activeTasks = taskList.filter((t) => t.status === 'running' || t.status === 'pending');
  const hasActiveTasks = activeTasks.length > 0;

  // 没有任务时不显示浮窗
  if (taskList.length === 0) return null;

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 10,
        right: 23,
        width: collapsed ? 260 : 400,
        maxHeight: collapsed ? 60 : 500,
        zIndex: 1000,
        boxShadow: token.boxShadowSecondary,
        borderRadius: token.borderRadiusLG,
        overflow: 'hidden',
        transition: 'all 0.3s ease',
      }}
    >
      <Card
        size="small"
        title={
          <Space>
            <ClockCircleOutlined />
            <span>后台任务</span>
            {hasActiveTasks && <Badge count={activeTasks.length} />}
          </Space>
        }
        extra={
          <Space>
            <Tooltip title="刷新">
              <Button
                type="text"
                size="small"
                icon={<ReloadOutlined />}
                onClick={loadTasks}
                loading={loading}
              />
            </Tooltip>
            {taskList.some(t => t.status === 'completed' || t.status === 'failed' || t.status === 'cancelled') && (
              <Popconfirm
                title="确认清理所有已结束的任务记录？"
                onConfirm={handleClearTasks}
                okText="确认"
                cancelText="取消"
              >
                <Tooltip title="清理已结束任务">
                  <Button
                    type="text"
                    size="small"
                    icon={<ClearOutlined />}
                  />
                </Tooltip>
              </Popconfirm>
            )}
            <Button
              type="text"
              size="small"
              icon={collapsed ? <UpOutlined /> : <DownOutlined />}
              onClick={() => {
                const newCollapsed = !collapsed;
                setCollapsed(newCollapsed);
                // 记录用户手动收起，防止自动展开覆盖
                userCollapsedRef.current = newCollapsed;
              }}
            />
          </Space>
        }
        bodyStyle={{
          padding: collapsed ? 0 : 12,
          maxHeight: collapsed ? 0 : 400,
          overflowY: 'auto',
          transition: 'all 0.3s ease',
        }}
      >
        {!collapsed && (
          <>
            {taskList.length === 0 ? (
              <Empty description="暂无任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <List
                size="small"
                dataSource={taskList}
                renderItem={(task: TaskStatus) => (
                  <List.Item
                    key={task.id}
                    style={{
                      padding: '8px 0',
                      borderBottom: `1px solid ${token.colorBorderSecondary}`,
                    }}
                  >
                    <div style={{ width: '100%' }}>
                      <div style={{ marginBottom: 4 }}>
                        <Space size={4} wrap>
                          {getTaskStatusTag(task.status)}
                          <Tag color="blue">{getTaskTypeLabel(task.task_type)}</Tag>
                        </Space>
                      </div>

                      {task.status_message && (
                        <div
                          style={{
                            fontSize: 12,
                            color: token.colorTextSecondary,
                            marginBottom: 4,
                          }}
                        >
                          {task.status_message}
                        </div>
                      )}

                      {(task.status === 'running' || task.status === 'pending') && (
                        <Progress
                          percent={task.progress}
                          size="small"
                          status={task.status === 'running' ? 'active' : 'normal'}
                          style={{ marginBottom: 4 }}
                        />
                      )}

                      {task.error_message && (
                        <div
                          style={{
                            fontSize: 12,
                            color: token.colorError,
                            marginBottom: 4,
                          }}
                        >
                          错误: {task.error_message}
                        </div>
                      )}

                      <div style={{ marginTop: 8 }}>
                        <Space size={4}>
                          {(task.status === 'running' || task.status === 'pending') && (
                            <Popconfirm
                              title="确认取消任务？"
                              onConfirm={() => handleCancelTask(task)}
                              okText="确认"
                              cancelText="取消"
                            >
                              <Button size="small" danger>
                                取消
                              </Button>
                            </Popconfirm>
                          )}
                          {(task.status === 'completed' ||
                            task.status === 'failed' ||
                            task.status === 'cancelled') && (
                              <Popconfirm
                                title="确认删除任务记录？"
                                onConfirm={() => handleDeleteTask(task.id)}
                                okText="确认"
                                cancelText="取消"
                              >
                                <Button size="small" icon={<DeleteOutlined />}>
                                  删除
                                </Button>
                              </Popconfirm>
                            )}
                        </Space>
                      </div>
                    </div>
                  </List.Item>
                )}
              />
            )}
          </>
        )}
      </Card>
    </div>
  );
};

export default FloatingTaskPanel;
