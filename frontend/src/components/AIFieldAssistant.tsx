import { useState, type ChangeEvent, type CSSProperties, type ReactNode } from 'react';
import { Button, Input, Modal, message, theme } from 'antd';
import type { ButtonProps } from 'antd';
import type { FormInstance } from 'antd/es/form';
import { HighlightOutlined } from '@ant-design/icons';
import { polishApi } from '../services/api';

const { TextArea } = Input;

export type AIFieldModalApi = ReturnType<typeof Modal.useModal>[0];

type ResultPreviewProps = {
  title: string;
  content: string;
  tone?: 'normal' | 'info' | 'primary';
  maxHeight?: number;
};

function ResultPreview({ title, content, tone = 'normal', maxHeight = 180 }: ResultPreviewProps) {
  const { token } = theme.useToken();
  const borderColor = tone === 'info'
    ? token.colorInfoBorder
    : tone === 'primary'
      ? token.colorPrimaryBorder
      : token.colorBorderSecondary;
  const background = tone === 'info'
    ? token.colorInfoBg
    : tone === 'primary'
      ? token.colorBgContainer
      : token.colorFillQuaternary;

  return (
    <div>
      <div style={{ fontWeight: 600, marginBottom: 6 }}>{title}</div>
      <div
        style={{
          maxHeight,
          overflowY: 'auto',
          whiteSpace: 'pre-wrap',
          lineHeight: 1.6,
          padding: '8px 10px',
          border: `1px solid ${borderColor}`,
          borderRadius: token.borderRadius,
          background,
          color: tone === 'normal' ? token.colorTextSecondary : undefined,
        }}
      >
        {content || '（空）'}
      </div>
    </div>
  );
}

type ConfirmAIResultOptions = {
  modalApi: AIFieldModalApi;
  label: string;
  aiText: string;
  currentValue?: string;
  sourceText?: string;
  instruction?: string;
  notice?: ReactNode;
  okText?: string;
  cancelText?: string;
  sourceTitle?: string;
  onApply: () => void;
};

export function confirmAIFieldResult({
  modalApi,
  label,
  aiText,
  currentValue,
  sourceText,
  instruction,
  notice = 'AI 结果需要确认后才会写入字段。',
  okText = '应用结果',
  cancelText,
  sourceTitle,
  onApply,
}: ConfirmAIResultOptions) {
  modalApi.confirm({
    title: `${label} AI结果`,
    icon: <HighlightOutlined />,
    width: 720,
    centered: true,
    okText,
    cancelText: cancelText || (currentValue ? '保留原文' : '暂不应用'),
    content: (
      <div style={{ marginTop: 12 }}>
        <div style={{ marginBottom: 12, color: 'var(--ant-color-text-secondary)' }}>
          {notice}
        </div>
        <div style={{ display: 'grid', gap: 12 }}>
          {instruction?.trim() && (
            <ResultPreview title="本次要求" content={instruction.trim()} tone="info" maxHeight={140} />
          )}
          {(currentValue || sourceText) && (
            <ResultPreview
              title={sourceTitle || (currentValue ? '当前内容' : '生成依据')}
              content={currentValue || sourceText || ''}
              maxHeight={160}
            />
          )}
          <ResultPreview title="AI结果" content={aiText} tone="primary" maxHeight={240} />
        </div>
      </div>
    ),
    onOk: onApply,
  });
}

export type AIFieldAssistButtonProps = {
  modalApi: AIFieldModalApi;
  label: string;
  getCurrentValue: () => string;
  getSourceText: () => string;
  buildDefaultInstruction: (mode: 'polish' | 'complete') => string;
  onApply: (aiText: string) => void;
  projectId?: string;
  provider?: string;
  model?: string;
  maxLength?: number;
  temperature?: {
    polish?: number;
    complete?: number;
  };
  buttonText?: string;
  buttonType?: ButtonProps['type'];
  buttonSize?: ButtonProps['size'];
  buttonStyle?: CSSProperties;
  filledHelpText?: string;
  emptyHelpText?: string;
  placeholder?: string;
  resultNotice?: ReactNode;
  sourceTitle?: string;
};

export function buildDefaultAIFieldInstruction(
  label: string,
  mode: 'polish' | 'complete',
  options?: {
    resultDescription?: string;
    contextName?: string;
  },
) {
  const resultDescription = options?.resultDescription || '文本';
  const contextName = options?.contextName || '上下文';

  if (mode === 'polish') {
    return `请润色「${label}」。保留原意和已有设定，不新增无依据内容，不输出解释，只输出处理后的${resultDescription}。`;
  }

  return `请根据${contextName}补全「${label}」。不要输出解释、标题或前后缀，只输出可直接填入该字段的${resultDescription}。`;
}

export function AIFieldAssistButton({
  modalApi,
  label,
  getCurrentValue,
  getSourceText,
  buildDefaultInstruction,
  onApply,
  projectId,
  provider,
  model,
  maxLength,
  temperature,
  buttonText = 'AI辅助',
  buttonType = 'link',
  buttonSize = 'small',
  buttonStyle,
  filledHelpText = '输入希望 AI 如何润色这段内容；留空则只做自然表达优化。',
  emptyHelpText = '当前字段为空，AI会参考已填写的上下文补全；也可以输入更具体的生成要求。',
  placeholder = '例如：更口语一点；压缩到一句话；保留关键词但改得更自然；不要新增设定...',
  resultNotice,
  sourceTitle,
}: AIFieldAssistButtonProps) {
  const [loading, setLoading] = useState(false);
  const { token } = theme.useToken();

  const runAI = async (sourceText: string, instruction: string, currentValue: string) => {
    const mode = currentValue ? 'polish' : 'complete';
    const trimmedInstruction = instruction.trim();
    const closeLoading = message.loading(`正在处理${label}...`, 0);

    try {
      setLoading(true);
      const result = await polishApi.polishText({
        original_text: sourceText,
        project_id: projectId,
        provider,
        model,
        temperature: mode === 'polish'
          ? temperature?.polish ?? 0.65
          : temperature?.complete ?? 0.8,
        instruction: trimmedInstruction || buildDefaultInstruction(mode),
      });

      const aiText = (result.polished_text || '').trim();
      if (!aiText) {
        message.warning('AI结果为空，请稍后重试');
        return;
      }

      const nextText = maxLength ? aiText.slice(0, maxLength) : aiText;
      confirmAIFieldResult({
        modalApi,
        label,
        aiText: nextText,
        currentValue,
        sourceText,
        instruction: trimmedInstruction,
        notice: resultNotice,
        sourceTitle,
        onApply: () => onApply(nextText),
      });
    } catch (error) {
      console.error(`${label} AI处理失败:`, error);
      message.error(`${label} AI处理失败`);
    } finally {
      closeLoading();
      setLoading(false);
    }
  };

  const handleClick = () => {
    const currentValue = getCurrentValue().trim();
    const sourceText = currentValue || getSourceText();
    let instruction = '';

    modalApi.confirm({
      title: `${label} AI处理要求`,
      icon: <HighlightOutlined />,
      width: 640,
      centered: true,
      okText: currentValue ? '开始润色' : '开始补全',
      cancelText: '取消',
      content: (
        <div style={{ marginTop: 12 }}>
          <div style={{ marginBottom: 12, color: token.colorTextSecondary }}>
            {currentValue ? filledHelpText : emptyHelpText}
          </div>
          <TextArea
            rows={4}
            placeholder={placeholder}
            autoFocus
            onChange={(event) => {
              instruction = event.target.value;
            }}
          />
          <div style={{ marginTop: 12 }}>
            <ResultPreview
              title={currentValue ? '当前内容' : '生成依据'}
              content={sourceText}
              maxHeight={120}
            />
          </div>
        </div>
      ),
      onOk: () => runAI(sourceText, instruction, currentValue),
    });
  };

  return (
    <Button
      type={buttonType}
      size={buttonSize}
      icon={<HighlightOutlined />}
      loading={loading}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        handleClick();
      }}
      style={buttonStyle}
    >
      {buttonText}
    </Button>
  );
}

export type PolishableTextAreaProps = {
  form: FormInstance;
  modalApi: AIFieldModalApi;
  name: string;
  label: string;
  rows: number;
  placeholder?: string;
  projectId?: string;
  provider?: string;
  model?: string;
  providerFieldName?: string;
  modelFieldName?: string;
  maxLength?: number;
  showCount?: boolean;
  value?: string;
  id?: string;
  disabled?: boolean;
  onChange?: (event: ChangeEvent<HTMLTextAreaElement>) => void;
  textAreaStyle?: CSSProperties;
};

export function PolishableTextArea({
  form,
  modalApi,
  name,
  label,
  rows,
  placeholder,
  projectId,
  provider,
  model,
  providerFieldName,
  modelFieldName,
  maxLength,
  showCount,
  value,
  id,
  disabled,
  onChange,
  textAreaStyle,
}: PolishableTextAreaProps) {
  const [isPolishing, setIsPolishing] = useState(false);
  const { token } = theme.useToken();

  const runPolish = async (currentValue: string, instruction: string) => {
    const closeLoading = message.loading(`正在润色${label}...`, 0);
    try {
      setIsPolishing(true);
      const trimmedInstruction = instruction.trim();
      const selectedProvider = providerFieldName ? form.getFieldValue(providerFieldName) : provider;
      const selectedModel = modelFieldName ? form.getFieldValue(modelFieldName) : model;
      const result = await polishApi.polishText({
        original_text: currentValue,
        project_id: projectId,
        provider: selectedProvider || undefined,
        model: selectedModel || undefined,
        temperature: 0.7,
        instruction: trimmedInstruction || undefined,
      });

      const polishedText = result.polished_text?.trim();
      if (!polishedText) {
        message.warning('润色结果为空，请稍后重试');
        return;
      }

      confirmAIFieldResult({
        modalApi,
        label,
        aiText: maxLength ? polishedText.slice(0, maxLength) : polishedText,
        currentValue,
        instruction: trimmedInstruction,
        notice: 'AI 已完成润色，确认后才会替换文本框内容。',
        okText: '应用润色结果',
        cancelText: '保留原文',
        sourceTitle: '原文',
        onApply: () => {
          form.setFieldsValue({ [name]: maxLength ? polishedText.slice(0, maxLength) : polishedText });
          message.success(`${label}已应用润色结果`);
        },
      });
    } catch (error) {
      console.error(`${label}润色失败:`, error);
      message.error(`${label}润色失败`);
    } finally {
      closeLoading();
      setIsPolishing(false);
    }
  };

  const handlePolish = () => {
    const currentValue = String(form.getFieldValue(name) || '').trim();
    if (!currentValue) {
      message.warning(`请先填写${label}`);
      return;
    }

    let instruction = '';
    modalApi.confirm({
      title: `${label}润色要求`,
      icon: <HighlightOutlined />,
      width: 640,
      centered: true,
      okText: '开始润色',
      cancelText: '取消',
      content: (
        <div style={{ marginTop: 12 }}>
          <div style={{ marginBottom: 12, color: token.colorTextSecondary }}>
            输入本次希望 AI 如何处理这段内容；留空则使用默认去 AI 味润色。
          </div>
          <TextArea
            rows={4}
            placeholder="例如：保留原意，只让表达更自然；压缩到两句话；强化时代感；不要新增设定..."
            autoFocus
            onChange={(event) => {
              instruction = event.target.value;
            }}
          />
          <div style={{ marginTop: 12 }}>
            <ResultPreview title="原文" content={currentValue} maxHeight={120} />
          </div>
        </div>
      ),
      onOk: () => runPolish(currentValue, instruction),
    });
  };

  return (
    <div style={{ position: 'relative' }}>
      <TextArea
        id={id}
        rows={rows}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        showCount={showCount}
        maxLength={maxLength}
        disabled={disabled}
        style={{ paddingRight: 44, ...textAreaStyle }}
      />
      <Button
        type="text"
        shape="circle"
        size="small"
        icon={<HighlightOutlined />}
        loading={isPolishing}
        disabled={disabled}
        aria-label={`润色${label}`}
        title={`润色${label}`}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          void handlePolish();
        }}
        style={{
          position: 'absolute',
          top: 8,
          right: 8,
          zIndex: 1,
          color: token.colorPrimary,
          background: token.colorBgElevated,
          border: `1px solid ${token.colorBorderSecondary}`,
          boxShadow: token.boxShadowTertiary,
        }}
      />
    </div>
  );
}
