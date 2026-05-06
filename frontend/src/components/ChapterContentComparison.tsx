import React, { useEffect, useMemo, useState } from 'react';
import { Modal, Button, Card, Input, Statistic, Row, Col, message, theme } from 'antd';
import { CheckOutlined, CloseOutlined, SwapOutlined } from '@ant-design/icons';
import ReactDiffViewer from 'react-diff-viewer-continued';
import { useThemeMode } from '../theme/useThemeMode';
import { taskMessage } from '../utils/taskMessage';

const { TextArea } = Input;

interface ChapterContentComparisonProps {
  visible: boolean;
  onClose: () => void;
  chapterId: string;
  chapterTitle: string;
  originalContent: string;
  newContent: string;
  wordCount: number;
  onApply: () => void;
  onDiscard: () => void;
}

const ChapterContentComparison: React.FC<ChapterContentComparisonProps> = ({
  visible,
  onClose,
  chapterId,
  chapterTitle,
  originalContent,
  newContent,
  onApply,
  onDiscard
}) => {
  const { token } = theme.useToken();
  const { resolvedMode } = useThemeMode();
  const [applying, setApplying] = useState(false);
  const [viewMode, setViewMode] = useState<'split' | 'unified'>('split');
  const [editedContent, setEditedContent] = useState(newContent);
  const [modal, contextHolder] = Modal.useModal();

  const originalWordCount = originalContent.length;
  const editedWordCount = editedContent.length;
  const wordCountDiff = editedWordCount - originalWordCount;
  const wordCountDiffPercent = ((wordCountDiff / originalWordCount) * 100).toFixed(1);
  const isDarkMode = resolvedMode === 'dark';
  useEffect(() => {
    setEditedContent(newContent);
  }, [newContent]);

  const diffViewerStyles = useMemo(() => ({
    variables: {
      light: {
        diffViewerBackground: token.colorBgContainer,
        diffViewerColor: token.colorText,
        diffViewerTitleBackground: token.colorBgElevated,
        diffViewerTitleColor: token.colorTextHeading,
        addedBackground: token.colorSuccessBg,
        addedColor: token.colorText,
        removedBackground: token.colorErrorBg,
        removedColor: token.colorText,
        wordAddedBackground: token.colorSuccessBorder,
        wordRemovedBackground: token.colorErrorBorder,
        addedGutterBackground: token.colorSuccessBg,
        removedGutterBackground: token.colorErrorBg,
        gutterBackground: token.colorFillQuaternary,
        gutterBackgroundDark: token.colorFillTertiary,
        highlightBackground: token.colorWarningBg,
        highlightGutterBackground: token.colorWarningBorder,
      },
      dark: {
        diffViewerBackground: token.colorBgContainer,
        diffViewerColor: token.colorText,
        diffViewerTitleBackground: token.colorBgElevated,
        diffViewerTitleColor: token.colorTextHeading,
        addedBackground: 'rgba(82, 196, 26, 0.16)',
        addedColor: token.colorText,
        removedBackground: 'rgba(255, 77, 79, 0.16)',
        removedColor: token.colorText,
        wordAddedBackground: 'rgba(82, 196, 26, 0.3)',
        wordRemovedBackground: 'rgba(255, 77, 79, 0.3)',
        addedGutterBackground: 'rgba(82, 196, 26, 0.12)',
        removedGutterBackground: 'rgba(255, 77, 79, 0.12)',
        gutterBackground: token.colorFillQuaternary,
        gutterBackgroundDark: token.colorFillSecondary,
        highlightBackground: 'rgba(250, 173, 20, 0.18)',
        highlightGutterBackground: 'rgba(250, 173, 20, 0.28)',
      },
    },
    line: {
      padding: '10px 2px',
      fontSize: '14px',
      lineHeight: '20px',
      whiteSpace: 'pre-wrap' as const,
      wordBreak: 'break-word' as const,
    },
  }), [token]);

  const handleApply = async () => {
    setApplying(true);
    try {
      const response = await fetch(`/api/chapters/${chapterId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedContent
        })
      });

      if (!response.ok) {
        throw new Error('应用新内容失败');
      }

      message.success('新内容已应用！');

      // 先调用 onApply 通知父组件刷新
      onApply();

      // 延迟触发章节分析，给父组件时间刷新
      setTimeout(async () => {
        try {
          const analysisResponse = await fetch(`/api/chapters/${chapterId}/analyze`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            }
          });

          if (analysisResponse.ok) {
            taskMessage.started('章节分析任务', { location: 'currentPage' });
          } else {
            message.warning('章节分析触发失败，您可以手动触发分析');
          }
        } catch (analysisError) {
          console.error('触发分析失败:', analysisError);
          message.warning('章节分析触发失败，您可以手动触发分析');
        }
      }, 500);

      onClose();
    } catch (error: unknown) {
      const err = error as Error;
      message.error(err.message || '应用失败');
    } finally {
      setApplying(false);
    }
  };

  const handleDiscard = () => {
    modal.confirm({
      title: '确认放弃',
      content: '确定要放弃新生成的内容吗？此操作不可恢复。',
      centered: true,
      okText: '确定放弃',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: () => {
        onDiscard();
        onClose();
        message.info('已放弃新内容');
      }
    });
  };

  return (
    <>
      {contextHolder}
      <Modal
      title={`内容对比 - ${chapterTitle}`}
      open={visible}
      onCancel={onClose}
      width="95%"
      centered
      style={{ maxWidth: 1600 }}
      footer={[
        <Button
          key="discard"
          danger
          icon={<CloseOutlined />}
          onClick={handleDiscard}
        >
          放弃新内容
        </Button>,
        <Button
          key="toggle"
          icon={<SwapOutlined />}
          onClick={() => setViewMode(viewMode === 'split' ? 'unified' : 'split')}
        >
          切换视图
        </Button>,
        <Button
          key="apply"
          type="primary"
          icon={<CheckOutlined />}
          loading={applying}
          onClick={handleApply}
        >
          应用新内容
        </Button>
      ]}
    >
      {/* 统计信息 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={6}>
            <Statistic
              title="原内容字数"
              value={originalWordCount}
              suffix="字"
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="新内容字数"
              value={editedWordCount}
              suffix="字"
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="字数变化"
              value={wordCountDiff}
              suffix="字"
              valueStyle={{ color: wordCountDiff > 0 ? 'var(--color-success)' : 'var(--color-error)' }}
              prefix={wordCountDiff > 0 ? '+' : ''}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="变化比例"
              value={wordCountDiffPercent}
              suffix="%"
              valueStyle={{ color: Math.abs(parseFloat(wordCountDiffPercent)) < 10 ? 'var(--color-primary)' : 'var(--color-warning)' }}
              prefix={wordCountDiff > 0 ? '+' : ''}
            />
          </Col>
        </Row>
      </Card>

      <Card size="small" title="新内容（可编辑）" style={{ marginBottom: 16 }}>
        <TextArea
          value={editedContent}
          onChange={(event) => setEditedContent(event.target.value)}
          rows={10}
          style={{ lineHeight: 1.8 }}
        />
      </Card>

      {/* 内容对比 */}
      <div style={{
        maxHeight: 'calc(90vh - 300px)',
        overflow: 'auto',
        border: `1px solid ${token.colorBorder}`,
        borderRadius: 8,
        background: token.colorBgContainer
      }}>
        <ReactDiffViewer
          oldValue={originalContent}
          newValue={editedContent}
          splitView={viewMode === 'split'}
          leftTitle="原内容"
          rightTitle="新内容"
          showDiffOnly={false}
          useDarkTheme={isDarkMode}
          styles={diffViewerStyles}
        />
      </div>
      </Modal>
    </>
  );
};

export default ChapterContentComparison;
