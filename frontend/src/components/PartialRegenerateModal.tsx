import React, { useState, useRef, useEffect } from 'react';
import { Modal, Input, Button, Space, Radio, InputNumber, Card, message, Alert, Spin, Typography, Divider, theme } from 'antd';
import { ThunderboltOutlined, CheckOutlined, ReloadOutlined, EditOutlined, LoadingOutlined } from '@ant-design/icons';
import { chapterApi } from '../services/api';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

interface PartialRegenerateModalProps {
  visible: boolean;
  chapterId: string;
  title?: string;
  selectedText: string;
  startPosition: number;
  endPosition: number;
  styleId?: number;
  onClose: () => void;
  onApply: (newText: string, startPosition: number, endPosition: number) => void;
}

type LengthMode = 'similar' | 'expand' | 'condense' | 'custom';

/**
 * 局部重写弹窗组件
 * 用于配置和执行选中文本的AI重写
 */
export const PartialRegenerateModal: React.FC<PartialRegenerateModalProps> = ({
  visible,
  chapterId,
  title = 'AI局部重写',
  selectedText,
  startPosition,
  endPosition,
  styleId,
  onClose,
  onApply,
}) => {
  const { token } = theme.useToken();
  const [userInstructions, setUserInstructions] = useState('');
  const [lengthMode, setLengthMode] = useState<LengthMode>('similar');
  const [customWordCount, setCustomWordCount] = useState<number>(selectedText.length);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedText, setGeneratedText] = useState('');
  const [hasGenerated, setHasGenerated] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const [appliedStartPosition, setAppliedStartPosition] = useState(startPosition);
  const [appliedEndPosition, setAppliedEndPosition] = useState(endPosition);
  const abortControllerRef = useRef<AbortController | null>(null);
  const generatedTextRef = useRef<HTMLDivElement>(null);

  // 重置状态
  useEffect(() => {
    if (visible) {
      setUserInstructions('');
      setLengthMode('similar');
      setCustomWordCount(selectedText.length);
      setIsGenerating(false);
      setGeneratedText('');
      setHasGenerated(false);
      setProgress(0);
      setProgressMessage('');
      setAppliedStartPosition(startPosition);
      setAppliedEndPosition(endPosition);
    }
  }, [visible, selectedText, startPosition, endPosition]);

  // 自动滚动到底部
  useEffect(() => {
    if (generatedTextRef.current && isGenerating) {
      generatedTextRef.current.scrollTop = generatedTextRef.current.scrollHeight;
    }
  }, [generatedText, isGenerating]);

  const handleGenerate = async () => {
    if (!userInstructions.trim()) {
      message.warning('请输入重写要求');
      return;
    }

    setIsGenerating(true);
    setGeneratedText('');
    setHasGenerated(false);
    setProgress(0);
    setProgressMessage('准备生成...');

    // 创建 AbortController 用于取消请求
    abortControllerRef.current?.abort();
    abortControllerRef.current = new AbortController();
    let receivedText = false;
    let handledError = false;
    let accumulatedText = '';

    try {
      await chapterApi.partialRegenerateStream(
        chapterId,
        {
          selected_text: selectedText,
          start_position: startPosition,
          end_position: endPosition,
          user_instructions: userInstructions,
          context_chars: 1000,
          style_id: styleId,
          length_mode: lengthMode,
          target_word_count: lengthMode === 'custom' ? customWordCount : undefined,
        },
        {
          onProgress: (msg, prog) => {
            setProgress(prog);
            setProgressMessage(msg);
          },
          onChunk: (content) => {
            accumulatedText += content;
            if (accumulatedText.trim()) {
              receivedText = true;
            }
            setGeneratedText(accumulatedText);
          },
          onResult: (data) => {
            const finalText = typeof data?.new_text === 'string' ? data.new_text : '';
            if (finalText.trim()) {
              receivedText = true;
              accumulatedText = finalText;
              setGeneratedText(finalText);
              setAppliedStartPosition(
                typeof data.start_position === 'number' ? data.start_position : startPosition
              );
              setAppliedEndPosition(
                typeof data.end_position === 'number' ? data.end_position : endPosition
              );
            }
            setProgress(100);
            setProgressMessage('生成完成');
            setHasGenerated(Boolean(finalText.trim()) || receivedText);
          },
          onError: (error) => {
            handledError = true;
            console.error('SSE错误:', error);
            message.error(error || '生成过程中发生错误');
            setHasGenerated(false);
            setIsGenerating(false);
            if (!accumulatedText.trim()) {
              setGeneratedText('');
            }
          },
          onComplete: () => {
            setIsGenerating(false);
            const hasUsableText = receivedText && accumulatedText.trim().length > 0;
            setHasGenerated(hasUsableText);
            if (!hasUsableText) {
              message.warning('AI未返回可用重写内容，请重新生成');
            }
          },
          signal: abortControllerRef.current.signal,
        }
      );
    } catch (error) {
      console.error('生成失败:', error);
      if ((error as Error).name !== 'AbortError' && !handledError) {
        message.error((error as Error).message || '生成失败，请重试');
      }
      setIsGenerating(false);
      setHasGenerated(false);
    } finally {
      abortControllerRef.current = null;
    }
  };

  const handleCancel = () => {
    if (isGenerating && abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsGenerating(false);
      message.info('已取消生成');
    }
    onClose();
  };

  const handleAccept = async () => {
    if (!generatedText.trim()) {
      message.warning('没有可应用的内容');
      return;
    }

      try {
        // 调用后端应用更改
        await chapterApi.applyPartialRegenerate(chapterId, {
          new_text: generatedText,
          start_position: appliedStartPosition,
          end_position: appliedEndPosition,
          original_text: selectedText,
        });

      message.success('已应用重写内容');
      onApply(generatedText, appliedStartPosition, appliedEndPosition);
      onClose();
    } catch (error) {
      console.error('应用失败:', error);
      message.error('应用失败，请重试');
    }
  };

  const handleRegenerate = () => {
    setGeneratedText('');
    setHasGenerated(false);
    setProgress(0);
    setProgressMessage('');
    handleGenerate();
  };

  const getLengthModeDescription = (mode: LengthMode): string => {
    const descriptions: Record<LengthMode, string> = {
      similar: '保持与原文相近的长度',
      expand: '扩展内容，增加更多细节',
      condense: '精简内容，保留核心要点',
      custom: '指定目标字数',
    };
    return descriptions[mode];
  };

  return (
    <Modal
      title={
        <Space>
          <EditOutlined style={{ color: token.colorPrimary }} />
          <span>{title}</span>
        </Space>
      }
      open={visible}
      onCancel={handleCancel}
      width={800}
      centered
      maskClosable={!isGenerating}
      closable={!isGenerating}
      keyboard={!isGenerating}
      footer={
        <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
          <Button onClick={handleCancel}>
            {isGenerating ? '停止生成' : '取消'}
          </Button>
          {!hasGenerated ? (
            <Button
              type="primary"
              icon={isGenerating ? <LoadingOutlined /> : <ThunderboltOutlined />}
              onClick={handleGenerate}
              loading={isGenerating}
              disabled={!userInstructions.trim()}
              style={{
                background: `linear-gradient(135deg, ${token.colorPrimary} 0%, ${token.colorPrimaryHover} 100%)`,
                border: 'none',
                boxShadow: token.boxShadowSecondary,
              }}
            >
              {isGenerating ? '生成中...' : '开始重写'}
            </Button>
          ) : (
            <>
              <Button
                icon={<ReloadOutlined />}
                onClick={handleRegenerate}
              >
                重新生成
              </Button>
              <Button
                type="primary"
                icon={<CheckOutlined />}
                onClick={handleAccept}
                style={{ background: token.colorSuccess, borderColor: token.colorSuccess }}
              >
                接受并应用
              </Button>
            </>
          )}
        </Space>
      }
      styles={{
        body: {
          maxHeight: 'calc(100vh - 200px)',
          overflowY: 'auto',
        },
      }}
    >
      {/* 原文展示 */}
      <Card
        size="small"
        title={
          <Space>
            <Text strong>原文内容</Text>
            <Text type="secondary">({selectedText.length}字)</Text>
          </Space>
        }
        style={{ marginBottom: 16 }}
        styles={{
          body: {
            maxHeight: 150,
            overflowY: 'auto',
            background: token.colorFillAlter,
          },
        }}
      >
        <Paragraph
          style={{
            margin: 0,
            whiteSpace: 'pre-wrap',
            color: token.colorText,
            lineHeight: 1.8,
          }}
        >
          {selectedText}
        </Paragraph>
      </Card>

      {/* 重写要求输入 */}
      <div style={{ marginBottom: 16 }}>
        <Text strong style={{ display: 'block', marginBottom: 8 }}>
          重写要求 <Text type="danger">*</Text>
        </Text>
        <TextArea
          value={userInstructions}
          onChange={(e) => setUserInstructions(e.target.value)}
          placeholder="请描述您希望如何重写这段内容，例如：&#10;- 让描写更加生动细腻&#10;- 增加环境氛围描写&#10;- 加强角色心理活动&#10;- 改变叙事节奏，更加紧凑&#10;- 添加对话内容"
          rows={4}
          disabled={isGenerating}
          style={{ resize: 'none' }}
        />
      </div>

      {/* 长度模式选择 */}
      <div style={{ marginBottom: 16 }}>
        <Text strong style={{ display: 'block', marginBottom: 8 }}>
          长度控制
        </Text>
        <Radio.Group
          value={lengthMode}
          onChange={(e) => setLengthMode(e.target.value)}
          disabled={isGenerating}
          buttonStyle="solid"
        >
          <Radio.Button value="similar">保持长度</Radio.Button>
          <Radio.Button value="expand">扩展内容</Radio.Button>
          <Radio.Button value="condense">精简内容</Radio.Button>
          <Radio.Button value="custom">自定义</Radio.Button>
        </Radio.Group>
        <div style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {getLengthModeDescription(lengthMode)}
          </Text>
        </div>
        {lengthMode === 'custom' && (
          <div style={{ marginTop: 12 }}>
            <Space>
              <Text>目标字数：</Text>
              <InputNumber
                value={customWordCount}
                onChange={(value) => setCustomWordCount(value || selectedText.length)}
                min={10}
                max={10000}
                step={50}
                disabled={isGenerating}
                addonAfter="字"
                style={{ width: 150 }}
              />
            </Space>
          </div>
        )}
      </div>

      <Divider style={{ margin: '16px 0' }} />

      {/* 生成结果展示 */}
      {(isGenerating || hasGenerated) && (
        <div>
          <div style={{ 
            display: 'flex', 
            justifyContent: 'space-between', 
            alignItems: 'center',
            marginBottom: 8 
          }}>
            <Space>
              <Text strong>重写结果</Text>
              {generatedText && (
                <Text type="secondary">({generatedText.length}字)</Text>
              )}
            </Space>
            {isGenerating && (
              <Space>
                <Spin indicator={<LoadingOutlined style={{ fontSize: 14 }} spin />} />
                <Text type="secondary">{progressMessage || '生成中...'}</Text>
              </Space>
            )}
          </div>

          {/* 进度条 */}
          {isGenerating && (
            <div style={{ marginBottom: 12 }}>
              <div
                style={{
                  height: 4,
                  background: token.colorFillTertiary,
                  borderRadius: 2,
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    height: '100%',
                    background: `linear-gradient(90deg, ${token.colorPrimary} 0%, ${token.colorPrimaryHover} 100%)`,
                    width: `${progress}%`,
                    transition: 'width 0.3s ease',
                    borderRadius: 2,
                  }}
                />
              </div>
            </div>
          )}

          <Card
            size="small"
            ref={generatedTextRef}
            style={{
              background: generatedText ? token.colorSuccessBg : token.colorFillAlter,
              border: generatedText ? `1px solid ${token.colorSuccessBorder}` : `1px solid ${token.colorBorder}`,
            }}
            styles={{
              body: {
                maxHeight: 250,
                overflowY: 'auto',
                minHeight: 100,
              },
            }}
          >
            {generatedText ? (
              <Paragraph
                style={{
                  margin: 0,
                  whiteSpace: 'pre-wrap',
                  lineHeight: 1.8,
                }}
              >
                {generatedText}
                {isGenerating && (
                  <span
                    style={{
                      display: 'inline-block',
                      width: 8,
                      height: 16,
                      background: token.colorPrimary,
                      marginLeft: 2,
                      animation: 'blink 1s infinite',
                    }}
                  />
                )}
              </Paragraph>
            ) : (
              <div style={{ textAlign: 'center', padding: 20, color: token.colorTextTertiary }}>
                {isGenerating ? '正在生成内容...' : '等待生成...'}
              </div>
            )}
          </Card>

          {hasGenerated && generatedText && (
            <Alert
              message="生成完成"
              description={
                <span>
                  原文 {selectedText.length} 字 → 新文 {generatedText.length} 字
                  {generatedText.length > selectedText.length && (
                    <Text type="success"> (+{generatedText.length - selectedText.length}字)</Text>
                  )}
                  {generatedText.length < selectedText.length && (
                    <Text type="warning"> ({generatedText.length - selectedText.length}字)</Text>
                  )}
                </span>
              }
              type="success"
              showIcon
              style={{ marginTop: 12 }}
            />
          )}
        </div>
      )}

      {/* 添加闪烁光标动画 */}
      <style>{`
        @keyframes blink {
          0%, 50% { opacity: 1; }
          51%, 100% { opacity: 0; }
        }
      `}</style>
    </Modal>
  );
};

export default PartialRegenerateModal;
