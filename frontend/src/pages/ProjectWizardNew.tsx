import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Form, Input, InputNumber, Select, Button, Card,
  Row, Col, Typography, Space, message, Radio, theme, Modal
} from 'antd';
import type { FormInstance } from 'antd/es/form';
import {
  RocketOutlined, ArrowLeftOutlined, CheckCircleOutlined, EditOutlined
} from '@ant-design/icons';
import { AIProjectGenerator, type GenerationConfig } from '../components/AIProjectGenerator';
import { projectApi } from '../services/api';
import type { WizardBasicInfo } from '../types';
import { AIFieldAssistButton, buildDefaultAIFieldInstruction } from '../components/AIFieldAssistant';

const { TextArea } = Input;
const { Title, Paragraph } = Typography;
type ModalApi = ReturnType<typeof Modal.useModal>[0];

const wizardFieldLabels: Partial<Record<keyof WizardBasicInfo, string>> = {
  title: '书名',
  description: '小说简介',
  theme: '主题',
  genre: '类型',
  world_time_period: '时间背景',
  world_location: '地理位置',
  world_atmosphere: '氛围基调',
  world_rules: '世界规则',
};

const stringifyGenre = (genre?: string | string[]) => {
  if (Array.isArray(genre)) return genre.join('、');
  return genre || '';
};

const buildWizardContext = (values: Partial<WizardBasicInfo>, activeLabel: string) => {
  const lines: string[] = [];
  const append = (name: keyof WizardBasicInfo, value?: unknown) => {
    if (value === undefined || value === null) return;
    const text = Array.isArray(value) ? value.join('、') : String(value).trim();
    if (text) {
      lines.push(`${wizardFieldLabels[name] || String(name)}：${text}`);
    }
  };

  append('title', values.title);
  append('description', values.description);
  append('theme', values.theme);
  append('genre', values.genre);
  append('world_time_period', values.world_time_period);
  append('world_location', values.world_location);
  append('world_atmosphere', values.world_atmosphere);
  append('world_rules', values.world_rules);
  append('narrative_perspective', values.narrative_perspective);

  return lines.length > 0
    ? `当前项目上下文：\n${lines.join('\n')}\n\n需要处理的字段：${activeLabel}`
    : `需要为新小说生成或润色字段：${activeLabel}`;
};

const parseTagResult = (text: string) => (
  text
    .replace(/[《》「」【】]/g, '')
    .split(/[,，、\n;；]/)
    .map(item => item.trim())
    .filter(Boolean)
    .slice(0, 5)
);

const makeAIFieldLabel = (
  form: FormInstance<WizardBasicInfo>,
  modalApi: ModalApi,
  name: keyof WizardBasicInfo,
  label: string,
  options?: { resultType?: 'text' | 'tags'; maxLength?: number },
) => (
  <Space size={6}>
    <span>{label}</span>
    <AIFieldAssistButton
      modalApi={modalApi}
      label={label}
      getCurrentValue={() => {
        const value = form.getFieldValue(name);
        return Array.isArray(value) ? value.join('、') : String(value || '').trim();
      }}
      getSourceText={() => buildWizardContext(form.getFieldsValue(true), label)}
      buildDefaultInstruction={(mode) => buildDefaultAIFieldInstruction(label, mode, {
        resultDescription: options?.resultType === 'tags'
          ? mode === 'complete' ? '标签列表，使用顿号分隔' : '标签列表'
          : '文本',
      })}
      onApply={(text) => {
        if (options?.resultType === 'tags') {
          const tags = parseTagResult(text);
          if (!tags.length) {
            message.warning('AI未返回可用标签');
            return;
          }
          form.setFieldsValue({ [name]: tags } as Partial<WizardBasicInfo>);
        } else {
          form.setFieldsValue({ [name]: options?.maxLength ? text.slice(0, options.maxLength) : text } as Partial<WizardBasicInfo>);
        }
        message.success(`${label}已应用AI结果`);
      }}
      maxLength={options?.resultType === 'tags' ? undefined : options?.maxLength}
      emptyHelpText="当前字段为空，AI会参考已填写的项目上下文补全；也可以输入更具体的生成要求。"
      placeholder="例如：更口语一点；压缩到一句话；强化世界观冲突；保留关键词但改得更自然..."
      buttonStyle={{ paddingInline: 4 }}
    />
  </Space>
);

export default function ProjectWizardNew() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [form] = Form.useForm();
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const { token } = theme.useToken();

  // 状态管理
  const [currentStep, setCurrentStep] = useState<'form' | 'generating'>('form');
  const [generationConfig, setGenerationConfig] = useState<GenerationConfig | null>(null);
  const [resumeProjectId, setResumeProjectId] = useState<string | null>(null);
  const [creationMode, setCreationMode] = useState<'ai' | 'manual'>('ai');
  const [isCreatingManual, setIsCreatingManual] = useState(false);
  const [modal, contextHolder] = Modal.useModal();

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // 检查URL参数,如果有project_id则恢复生成
  useEffect(() => {
    const projectId = searchParams.get('project_id');
    if (projectId) {
      setResumeProjectId(projectId);
      handleResumeGeneration(projectId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // 恢复未完成项目的生成
  const handleResumeGeneration = async (projectId: string) => {
    try {
      const response = await fetch(`/api/projects/${projectId}`, {
        credentials: 'include'
      });
      if (!response.ok) {
        throw new Error('获取项目信息失败');
      }
      const project = await response.json();

      const config: GenerationConfig = {
        title: project.title,
        description: project.description || '',
        theme: project.theme || '',
        genre: project.genre || '',
        narrative_perspective: project.narrative_perspective || '第三人称',
        target_words: project.target_words || 100000,
        chapter_count: 3,
        character_count: project.character_count || 5,
      };

      setGenerationConfig(config);
      setCurrentStep('generating');
    } catch (error) {
      console.error('恢复生成失败:', error);
      message.error('恢复生成失败,请重试');
      navigate('/');
    }
  };

  // 开始生成流程
  const handleAutoGenerate = async (values: WizardBasicInfo) => {
    const config: GenerationConfig = {
      title: values.title,
      description: values.description || '',
      theme: values.theme || '',
      genre: values.genre || '',
      narrative_perspective: values.narrative_perspective || '第三人称',
      target_words: values.target_words || 100000,
      chapter_count: 3, // 默认生成3章大纲
      character_count: values.character_count || 5,
      outline_mode: values.outline_mode || 'one-to-many', // 添加大纲模式
    };

    setGenerationConfig(config);
    setCurrentStep('generating');
  };

  // 纯手动建书：只创建项目基础数据，不触发AI向导生成
  const handleManualCreate = async (values: WizardBasicInfo) => {
    setIsCreatingManual(true);
    try {
      const project = await projectApi.createProject({
        title: values.title,
        description: values.description?.trim() || '',
        theme: values.theme?.trim() || '',
        genre: stringifyGenre(values.genre),
        target_words: values.target_words || 100000,
        outline_mode: values.outline_mode || 'one-to-one',
        wizard_status: 'completed',
        wizard_step: 4,
        world_time_period: values.world_time_period?.trim() || '',
        world_location: values.world_location?.trim() || '',
        world_atmosphere: values.world_atmosphere?.trim() || '',
        world_rules: values.world_rules?.trim() || '',
        chapter_count: values.chapter_count || 0,
        narrative_perspective: values.narrative_perspective || '第三人称',
        character_count: 0,
      });

      message.success(`《${project.title}》已创建，可开始手动搭建设定`);
      navigate(`/project/${project.id}/world-setting`);
    } catch (error) {
      console.error('手动创建项目失败:', error);
      message.error('创建项目失败，请稍后重试');
    } finally {
      setIsCreatingManual(false);
    }
  };

  const handleSubmit = async (values: WizardBasicInfo) => {
    if ((values.creation_mode || creationMode) === 'manual') {
      await handleManualCreate(values);
      return;
    }

    await handleAutoGenerate(values);
  };

  // 生成完成回调
  const handleComplete = (projectId: string) => {
    console.log('项目创建完成:', projectId);
  };

  // 返回表单页面
  const handleBack = () => {
    setCurrentStep('form');
    setGenerationConfig(null);
  };

  // 渲染表单页面
  const renderForm = () => (
    <Card>
      <Title level={isMobile ? 4 : 3} style={{ marginBottom: 24 }}>
        创建新项目
      </Title>
      <Paragraph type="secondary" style={{ marginBottom: 32 }}>
        可以选择让AI自动搭建基础内容，也可以纯手动创建空白项目，先自己定好框架再逐步使用AI补全。
      </Paragraph>

      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        initialValues={{
          creation_mode: 'ai',
          genre: ['玄幻'],
          chapter_count: 30,
          narrative_perspective: '第三人称',
          character_count: 5,
          target_words: 100000,
          outline_mode: 'one-to-one', // 默认为传统模式（1-1）
        }}
      >
        <Form.Item
          label="创建模式"
          name="creation_mode"
          rules={[{ required: true, message: '请选择创建模式' }]}
        >
          <Radio.Group
            size="large"
            onChange={(event) => setCreationMode(event.target.value)}
            style={{ width: '100%' }}
          >
            <Row gutter={[16, 16]}>
              <Col xs={24} sm={12}>
                <Card
                  hoverable
                  style={{ borderWidth: 2, height: '100%' }}
                  onClick={() => {
                    form.setFieldValue('creation_mode', 'ai');
                    setCreationMode('ai');
                  }}
                >
                  <Radio value="ai" style={{ width: '100%' }}>
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <div style={{ fontSize: 16, fontWeight: 'bold' }}>
                        <RocketOutlined style={{ marginRight: 8, color: token.colorPrimary }} />
                        AI自动搭建
                      </div>
                      <div style={{ fontSize: 12, color: token.colorTextSecondary }}>
                        自动生成世界观、职业体系、角色和大纲节点
                      </div>
                    </Space>
                  </Radio>
                </Card>
              </Col>

              <Col xs={24} sm={12}>
                <Card
                  hoverable
                  style={{ borderWidth: 2, height: '100%' }}
                  onClick={() => {
                    form.setFieldValue('creation_mode', 'manual');
                    setCreationMode('manual');
                  }}
                >
                  <Radio value="manual" style={{ width: '100%' }}>
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <div style={{ fontSize: 16, fontWeight: 'bold' }}>
                        <EditOutlined style={{ marginRight: 8, color: token.colorSuccess }} />
                        纯手动建书
                      </div>
                      <div style={{ fontSize: 12, color: token.colorTextSecondary }}>
                        只创建项目和基础设定，不强制进入AI生成步骤
                      </div>
                    </Space>
                  </Radio>
                </Card>
              </Col>
            </Row>
          </Radio.Group>
        </Form.Item>

        <Form.Item
          label={makeAIFieldLabel(form, modal, 'title', '书名', { maxLength: 80 })}
          name="title"
          rules={[{ required: true, message: '请输入书名' }]}
        >
          <Input placeholder="输入你的小说标题" size="large" />
        </Form.Item>

        <Form.Item
          label={makeAIFieldLabel(form, modal, 'description', '小说简介', { maxLength: 300 })}
          name="description"
          rules={creationMode === 'ai' ? [{ required: true, message: '请输入小说简介' }] : []}
        >
          <TextArea
            rows={3}
            placeholder={creationMode === 'manual' ? '可先简单写，也可以留空进入项目后再补...' : '用一段话介绍你的小说...'}
            showCount
            maxLength={300}
          />
        </Form.Item>

        <Form.Item
          label={makeAIFieldLabel(form, modal, 'theme', '主题', { maxLength: 500 })}
          name="theme"
          rules={creationMode === 'ai' ? [{ required: true, message: '请输入主题' }] : []}
        >
          <TextArea
            rows={4}
            placeholder={creationMode === 'manual' ? '写下你想先固定的核心主题、卷名、卖点或约束...' : '描述你的小说主题...'}
            showCount
            maxLength={500}
          />
        </Form.Item>

        <Form.Item
          label={makeAIFieldLabel(form, modal, 'genre', '类型', { resultType: 'tags' })}
          name="genre"
          rules={creationMode === 'ai' ? [{ required: true, message: '请选择小说类型' }] : []}
        >
          <Select
            mode="tags"
            placeholder="选择或输入类型标签（如：玄幻、都市、修仙）"
            size="large"
            tokenSeparators={[',']}
            maxTagCount={5}
          >
            <Select.Option value="玄幻">玄幻</Select.Option>
            <Select.Option value="都市">都市</Select.Option>
            <Select.Option value="历史">历史</Select.Option>
            <Select.Option value="科幻">科幻</Select.Option>
            <Select.Option value="武侠">武侠</Select.Option>
            <Select.Option value="仙侠">仙侠</Select.Option>
            <Select.Option value="奇幻">奇幻</Select.Option>
            <Select.Option value="悬疑">悬疑</Select.Option>
            <Select.Option value="言情">言情</Select.Option>
            <Select.Option value="修仙">修仙</Select.Option>
          </Select>
        </Form.Item>

        {creationMode === 'manual' && (
          <Card
            size="small"
            title="手动框架设定"
            style={{ marginBottom: 24 }}
            styles={{ body: { paddingBottom: 8 } }}
          >
            <Form.Item
              label={makeAIFieldLabel(form, modal, 'world_time_period', '时间背景')}
              name="world_time_period"
            >
              <TextArea
                rows={2}
                placeholder="例如：近未来、架空王朝、1916年北海、末日后第七年..."
                showCount
                maxLength={500}
              />
            </Form.Item>

            <Form.Item
              label={makeAIFieldLabel(form, modal, 'world_location', '地理位置')}
              name="world_location"
            >
              <TextArea
                rows={2}
                placeholder="故事主要发生地点、势力版图、空间结构..."
                showCount
                maxLength={500}
              />
            </Form.Item>

            <Form.Item
              label={makeAIFieldLabel(form, modal, 'world_atmosphere', '氛围基调')}
              name="world_atmosphere"
            >
              <TextArea
                rows={3}
                placeholder="整体气质、叙事风味、冲突强度、读者预期..."
                showCount
                maxLength={800}
              />
            </Form.Item>

            <Form.Item
              label={makeAIFieldLabel(form, modal, 'world_rules', '世界规则')}
              name="world_rules"
            >
              <TextArea
                rows={4}
                placeholder="力量体系、科技水平、社会规则、禁忌、核心矛盾..."
                showCount
                maxLength={1200}
              />
            </Form.Item>
          </Card>
        )}

        <Form.Item
          label="大纲章节模式"
          name="outline_mode"
          rules={[{ required: true, message: '请选择大纲章节模式' }]}
          tooltip="创建后不可更改，请根据创作习惯选择"
        >
          <Radio.Group size="large">
            <Row gutter={16}>
              <Col xs={24} sm={12}>
                <Card
                  hoverable
                  style={{
                    // borderColor: form.getFieldValue('outline_mode') === 'one-to-one' ? token.colorPrimary : token.colorBorder,
                    borderWidth: 2,
                    height: '100%',
                  }}
                  onClick={() => form.setFieldValue('outline_mode', 'one-to-one')}
                >
                  <Radio value="one-to-one" style={{ width: '100%' }}>
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <div style={{ fontSize: 16, fontWeight: 'bold' }}>
                        <CheckCircleOutlined style={{ marginRight: 8, color: token.colorSuccess }} />
                        传统模式 (1→1)
                      </div>
                      <div style={{ fontSize: 12, color: token.colorTextSecondary }}>
                        一个大纲对应一个章节，简单直接
                      </div>
                      <div style={{ fontSize: 11, color: token.colorTextTertiary }}>
                        💡 适合：简单剧情、快速创作、短篇小说
                      </div>
                    </Space>
                  </Radio>
                </Card>
              </Col>

              <Col xs={24} sm={12}>
                <Card
                  hoverable
                  style={{
                    // borderColor: form.getFieldValue('outline_mode') === 'one-to-many' ? token.colorPrimary : token.colorBorder,
                    borderWidth: 2,
                    height: '100%',
                  }}
                  onClick={() => form.setFieldValue('outline_mode', 'one-to-many')}
                >
                  <Radio value="one-to-many" style={{ width: '100%' }}>
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <div style={{ fontSize: 16, fontWeight: 'bold' }}>
                        <CheckCircleOutlined style={{ marginRight: 8, color: token.colorSuccess }} />
                        细化模式 (1→N) 推荐
                      </div>
                      <div style={{ fontSize: 12, color: token.colorTextSecondary }}>
                        一个大纲可展开为多个章节，灵活控制
                      </div>
                      <div style={{ fontSize: 11, color: token.colorTextTertiary }}>
                        💡 适合：复杂剧情、长篇创作、需要细化控制
                      </div>
                    </Space>
                  </Radio>
                </Card>
              </Col>
            </Row>
          </Radio.Group>
        </Form.Item>

        <Row gutter={16}>
          <Col xs={24} sm={12}>
            <Form.Item
              label="叙事视角"
              name="narrative_perspective"
              rules={[{ required: true, message: '请选择叙事视角' }]}
            >
              <Select size="large" placeholder="选择小说的叙事视角">
                <Select.Option value="第一人称">第一人称</Select.Option>
                <Select.Option value="第三人称">第三人称</Select.Option>
                <Select.Option value="全知视角">全知视角</Select.Option>
              </Select>
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            {creationMode === 'ai' ? (
              <Form.Item
                label="角色数量"
                name="character_count"
                rules={[{ required: true, message: '请输入角色数量' }]}
              >
                <InputNumber
                  min={3}
                  max={20}
                  style={{ width: '100%' }}
                  size="large"
                  addonAfter="个"
                  placeholder="AI生成的角色数量"
                />
              </Form.Item>
            ) : (
              <Form.Item
                label="计划章节数"
                name="chapter_count"
              >
                <InputNumber
                  min={0}
                  style={{ width: '100%' }}
                  size="large"
                  addonAfter="章"
                  placeholder="可选，后续可调整"
                />
              </Form.Item>
            )}
          </Col>
        </Row>

        <Form.Item
          label="目标字数"
          name="target_words"
          rules={[{ required: true, message: '请输入目标字数' }]}
        >
          <InputNumber
            min={10000}
            style={{ width: '100%' }}
            size="large"
            addonAfter="字"
            placeholder="整部小说的目标字数"
          />
        </Form.Item>

        <Form.Item>
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Button
              type="primary"
              htmlType="submit"
              size="large"
              block
              icon={<RocketOutlined />}
              loading={isCreatingManual}
            >
              {creationMode === 'manual' ? '创建空白项目' : '开始创建项目'}
            </Button>
            <Button
              size="large"
              block
              onClick={() => navigate('/')}
            >
              返回首页
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  );

  return (
    <div style={{
      minHeight: '100dvh',
      background: token.colorBgBase,
    }}>
      {contextHolder}
      {/* 顶部标题栏 - 固定不滚动 */}
      <div style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        background: token.colorPrimary,
        boxShadow: `0 6px 20px color-mix(in srgb, ${token.colorPrimary} 30%, transparent)`,
      }}>
        <div style={{
          maxWidth: 1200,
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: isMobile ? '12px 16px' : '16px 24px',
        }}>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/')}
            size={isMobile ? 'middle' : 'large'}
            disabled={currentStep === 'generating'}
            style={{
              background: `color-mix(in srgb, ${token.colorWhite} 20%, transparent)`,
              borderColor: `color-mix(in srgb, ${token.colorWhite} 30%, transparent)`,
              color: token.colorWhite,
            }}
          >
            {isMobile ? '返回' : '返回首页'}
          </Button>

          <Title level={isMobile ? 4 : 2} style={{
            margin: 0,
            color: token.colorWhite,
            textShadow: '0 2px 4px color-mix(in srgb, var(--ant-color-black) 18%, transparent)',
          }}>
            <RocketOutlined style={{ marginRight: 8 }} />
            项目创建向导
          </Title>

          <div style={{ width: isMobile ? 60 : 120 }}></div>
        </div>
      </div>

      {/* 内容区域 */}
      <div style={{
        maxWidth: 800,
        margin: '0 auto',
        padding: isMobile ? '8px 12px 12px' : '12px 20px 16px',
      }}>
        {currentStep === 'form' && renderForm()}
        {currentStep === 'generating' && generationConfig && (
          <AIProjectGenerator
            config={generationConfig}
            storagePrefix="wizard"
            onComplete={handleComplete}
            onBack={handleBack}
            isMobile={isMobile}
            resumeProjectId={resumeProjectId || undefined}
          />
        )}
      </div>
    </div>
  );
}
