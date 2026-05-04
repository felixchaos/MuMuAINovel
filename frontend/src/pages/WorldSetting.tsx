import { Card, Descriptions, Empty, Typography, Button, Modal, Form, Input, message, Flex, InputNumber, Select, theme } from 'antd';
import { GlobalOutlined, EditOutlined, SyncOutlined, FormOutlined, HighlightOutlined } from '@ant-design/icons';
import { useState, type ChangeEvent, type CSSProperties } from 'react';
import type { FormInstance } from 'antd/es/form';
import { useStore } from '../store';
import { worldSettingCardStyles } from '../components/CardStyles';
import { projectApi, wizardStreamApi, polishApi } from '../services/api';
import { SSELoadingOverlay } from '../components/SSELoadingOverlay';

const { Title, Paragraph } = Typography;
const { TextArea } = Input;
type ModalApi = ReturnType<typeof Modal.useModal>[0];

interface PolishableWorldTextAreaProps {
  form: FormInstance;
  modalApi: ModalApi;
  projectId?: string;
  name: string;
  label: string;
  rows: number;
  placeholder: string;
  maxLength?: number;
  showCount?: boolean;
  value?: string;
  onChange?: (event: ChangeEvent<HTMLTextAreaElement>) => void;
}

function PolishableWorldTextArea({
  form,
  modalApi,
  projectId,
  name,
  label,
  rows,
  placeholder,
  maxLength,
  showCount,
  value,
  onChange,
}: PolishableWorldTextAreaProps) {
  const [isPolishing, setIsPolishing] = useState(false);
  const { token } = theme.useToken();

  const runPolish = async (currentValue: string, instruction: string) => {
    const closeLoading = message.loading(`正在润色${label}...`, 0);
    try {
      setIsPolishing(true);
      const trimmedInstruction = instruction.trim();
      const result = await polishApi.polishText({
        original_text: currentValue,
        project_id: projectId,
        temperature: 0.7,
        instruction: trimmedInstruction || undefined,
      });

      const polishedText = result.polished_text?.trim();
      if (!polishedText) {
        message.warning('润色结果为空，请稍后重试');
        return;
      }

      modalApi.confirm({
        title: `${label}润色结果`,
        icon: <HighlightOutlined />,
        width: 720,
        centered: true,
        okText: '应用润色结果',
        cancelText: '保留原文',
        content: (
          <div style={{ marginTop: 12 }}>
            <div style={{ marginBottom: 14, color: token.colorTextSecondary }}>
              AI 已完成润色，确认后才会替换文本框内容。
            </div>
            <div style={{ display: 'grid', gap: 12 }}>
              {trimmedInstruction && (
                <div>
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>本次要求</div>
                  <div
                    style={{
                      whiteSpace: 'pre-wrap',
                      lineHeight: 1.6,
                      padding: '8px 10px',
                      border: `1px solid ${token.colorInfoBorder}`,
                      borderRadius: token.borderRadius,
                      background: token.colorInfoBg,
                    }}
                  >
                    {trimmedInstruction}
                  </div>
                </div>
              )}
              <div>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>原文</div>
                <div
                  style={{
                    maxHeight: 160,
                    overflowY: 'auto',
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.6,
                    padding: '8px 10px',
                    border: `1px solid ${token.colorBorderSecondary}`,
                    borderRadius: token.borderRadius,
                    background: token.colorFillQuaternary,
                  }}
                >
                  {currentValue}
                </div>
              </div>
              <div>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>润色结果</div>
                <div
                  style={{
                    maxHeight: 220,
                    overflowY: 'auto',
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.6,
                    padding: '8px 10px',
                    border: `1px solid ${token.colorPrimaryBorder}`,
                    borderRadius: token.borderRadius,
                    background: token.colorBgContainer,
                  }}
                >
                  {polishedText}
                </div>
              </div>
            </div>
          </div>
        ),
        onOk: () => {
          form.setFieldsValue({ [name]: polishedText });
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
          <div
            style={{
              marginTop: 12,
              maxHeight: 120,
              overflowY: 'auto',
              whiteSpace: 'pre-wrap',
              lineHeight: 1.6,
              padding: '8px 10px',
              border: `1px solid ${token.colorBorderSecondary}`,
              borderRadius: token.borderRadius,
              background: token.colorFillQuaternary,
              color: token.colorTextSecondary,
            }}
          >
            {currentValue}
          </div>
        </div>
      ),
      onOk: () => runPolish(currentValue, instruction),
    });
  };

  const textAreaStyle: CSSProperties = {
    paddingRight: 44,
  };

  return (
    <div style={{ position: 'relative' }}>
      <TextArea
        rows={rows}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        showCount={showCount}
        maxLength={maxLength}
        style={textAreaStyle}
      />
      <Button
        type="text"
        shape="circle"
        size="small"
        icon={<HighlightOutlined />}
        loading={isPolishing}
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

export default function WorldSetting() {
  const { currentProject, setCurrentProject } = useStore();
  const [isEditModalVisible, setIsEditModalVisible] = useState(false);
  const [editForm] = Form.useForm();
  const [isSaving, setIsSaving] = useState(false);
  const [isEditProjectModalVisible, setIsEditProjectModalVisible] = useState(false);
  const [editProjectForm] = Form.useForm();
  const [isSavingProject, setIsSavingProject] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [regenerateProgress, setRegenerateProgress] = useState(0);
  const [regenerateMessage, setRegenerateMessage] = useState('');
  const [isPreviewModalVisible, setIsPreviewModalVisible] = useState(false);
  const [newWorldData, setNewWorldData] = useState<{
    time_period: string;
    location: string;
    atmosphere: string;
    rules: string;
  } | null>(null);
  const [isSavingPreview, setIsSavingPreview] = useState(false);
  const [modal, contextHolder] = Modal.useModal();
  const { token } = theme.useToken();

  // AI重新生成世界观
  const handleRegenerate = async () => {
    if (!currentProject) return;

    modal.confirm({
      title: '确认重新生成',
      content: '确定要使用AI重新生成世界观设定吗？这将替换当前的世界观内容。',
      centered: true,
      okText: '确认重新生成',
      cancelText: '取消',
      onOk: async () => {
        setIsRegenerating(true);
        setRegenerateProgress(0);
        setRegenerateMessage('准备重新生成世界观...');

        try {
          await wizardStreamApi.regenerateWorldBuildingStream(
            currentProject.id,
            {},
            {
              onProgress: (msg: string, progress: number) => {
                setRegenerateProgress(progress);
                setRegenerateMessage(msg);
              },
              onChunk: (chunk: string) => {
                // 可以在这里显示生成的内容片段（可选）
                console.log('生成片段:', chunk);
              },
              onResult: (result: { time_period: string; location: string; atmosphere: string; rules: string }) => {
                // 保存新生成的数据
                const newData = {
                  time_period: result.time_period,
                  location: result.location,
                  atmosphere: result.atmosphere,
                  rules: result.rules,
                };
                setNewWorldData(newData);
              },
              onError: (errorMsg: string) => {
                console.error('重新生成失败:', errorMsg);
                message.error(errorMsg || '重新生成失败，请重试');
              },
              onComplete: () => {
                setIsRegenerating(false);
                setRegenerateProgress(0);
                setRegenerateMessage('');
                // 显示预览对话框
                setIsPreviewModalVisible(true);
              }
            }
          );
        } catch (error) {
          console.error('重新生成出错:', error);
          message.error('重新生成出错，请重试');
          setIsRegenerating(false);
          setRegenerateProgress(0);
          setRegenerateMessage('');
        }
      }
    });
  };

  // 确认保存重新生成的内容
  const handleConfirmSave = async () => {
    if (!currentProject || !newWorldData) return;

    setIsSavingPreview(true);
    try {
      const updatedProject = await projectApi.updateProject(currentProject.id, {
        world_time_period: newWorldData.time_period,
        world_location: newWorldData.location,
        world_atmosphere: newWorldData.atmosphere,
        world_rules: newWorldData.rules,
      });

      setCurrentProject(updatedProject);
      message.success('世界观已更新！');
      setIsPreviewModalVisible(false);
      setNewWorldData(null);
    } catch (error) {
      console.error('保存失败:', error);
      message.error('保存失败，请重试');
    } finally {
      setIsSavingPreview(false);
    }
  };

  // 取消保存，关闭预览
  const handleCancelSave = () => {
    setIsPreviewModalVisible(false);
    setNewWorldData(null);
    message.info('已取消，保持原有内容');
  };

  if (!currentProject) return null;

  // 检查是否有世界设定信息
  const hasWorldSetting = currentProject.world_time_period ||
    currentProject.world_location ||
    currentProject.world_atmosphere ||
    currentProject.world_rules;

  if (!hasWorldSetting) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* 固定头部 */}
        <div style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          backgroundColor: token.colorBgContainer,
          padding: '16px 0',
          marginBottom: 16,
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
          display: 'flex',
          alignItems: 'center'
        }}>
          <GlobalOutlined style={{ fontSize: 24, marginRight: 12, color: token.colorPrimary }} />
          <h2 style={{ margin: 0 }}>世界设定</h2>
        </div>

        {/* 可滚动内容区域 */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <Empty
            description="暂无世界设定信息"
            style={{ marginTop: 60 }}
          >
            <Paragraph type="secondary">
              世界设定信息在创建项目向导中生成，用于构建小说的世界观背景。
            </Paragraph>
          </Empty>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {contextHolder}
      {/* 固定头部 */}
      <div style={{
        position: 'sticky',
        top: 0,
        zIndex: 10,
        backgroundColor: token.colorBgContainer,
        padding: '16px 0',
        marginBottom: 24,
        borderBottom: `1px solid ${token.colorBorderSecondary}`
      }}>
        <Flex
          justify="space-between"
          align="flex-start"
          gap={12}
          wrap="wrap"
        >
          <div style={{ display: 'flex', alignItems: 'center', minWidth: 'fit-content' }}>
            <GlobalOutlined style={{ fontSize: 24, marginRight: 12, color: token.colorPrimary }} />
            <h2 style={{ margin: 0, whiteSpace: 'nowrap' }}>世界设定</h2>
          </div>
          <Flex gap={8} wrap="wrap" style={{ flex: '0 1 auto' }}>
            <Button
              icon={<SyncOutlined />}
              onClick={handleRegenerate}
              disabled={isRegenerating}
              style={{
                minWidth: 'fit-content',
                flex: '1 1 auto'
              }}
            >
              <span className="button-text-mobile">AI重新生成</span>
            </Button>
            <Button
              type="primary"
              icon={<FormOutlined />}
              onClick={() => {
                editProjectForm.setFieldsValue({
                  title: currentProject.title || '',
                  description: currentProject.description || '',
                  theme: currentProject.theme || '',
                  genre: currentProject.genre || '',
                  narrative_perspective: currentProject.narrative_perspective || '',
                  target_words: currentProject.target_words || 0,
                });
                setIsEditProjectModalVisible(true);
              }}
              style={{
                minWidth: 'fit-content',
                flex: '1 1 auto'
              }}
            >
              <span className="button-text-mobile">编辑基础信息</span>
            </Button>
            <Button
              type="primary"
              icon={<EditOutlined />}
              onClick={() => {
                editForm.setFieldsValue({
                  world_time_period: currentProject.world_time_period || '',
                  world_location: currentProject.world_location || '',
                  world_atmosphere: currentProject.world_atmosphere || '',
                  world_rules: currentProject.world_rules || '',
                });
                setIsEditModalVisible(true);
              }}
              style={{
                minWidth: 'fit-content',
                flex: '1 1 auto'
              }}
            >
              <span className="button-text-mobile">编辑世界观</span>
            </Button>
          </Flex>
        </Flex>
      </div>

      {/* 可滚动内容区域 */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        <Card
          style={{
            ...worldSettingCardStyles.sectionCard,
            marginBottom: 16
          }}
          title={
            <span style={{ fontSize: 18, fontWeight: 500 }}>
              基础信息
            </span>
          }
        >
          <Descriptions bordered column={1} styles={{ label: { width: 120, fontWeight: 500 } }}>
            <Descriptions.Item label="小说名称">{currentProject.title}</Descriptions.Item>
            {currentProject.description && (
              <Descriptions.Item label="小说简介">{currentProject.description}</Descriptions.Item>
            )}
            <Descriptions.Item label="小说主题">{currentProject.theme || '未设定'}</Descriptions.Item>
            <Descriptions.Item label="小说类型">{currentProject.genre || '未设定'}</Descriptions.Item>
            <Descriptions.Item label="叙事视角">{currentProject.narrative_perspective || '未设定'}</Descriptions.Item>
            <Descriptions.Item label="目标字数">
              {currentProject.target_words ? `${currentProject.target_words.toLocaleString()} 字` : '未设定'}
            </Descriptions.Item>
          </Descriptions>
        </Card>

        <Card
          style={{
            ...worldSettingCardStyles.sectionCard,
            marginBottom: 16
          }}
          title={
            <span style={{ fontSize: 18, fontWeight: 500 }}>
              <GlobalOutlined style={{ marginRight: 8 }} />
              小说世界观
            </span>
          }
        >
          <div style={{ padding: '16px 0' }}>
            {currentProject.world_time_period && (
              <div style={{ marginBottom: 24 }}>
                <Title level={5} style={{ color: token.colorPrimary, marginBottom: 12 }}>
                  时间设定
                </Title>
                <Paragraph style={{
                  fontSize: 15,
                  lineHeight: 1.8,
                  padding: 16,
                  background: token.colorBgLayout,
                  borderRadius: 8,
                  borderLeft: `4px solid ${token.colorPrimary}`
                }}>
                  {currentProject.world_time_period}
                </Paragraph>
              </div>
            )}

            {currentProject.world_location && (
              <div style={{ marginBottom: 24 }}>
                <Title level={5} style={{ color: token.colorSuccess, marginBottom: 12 }}>
                  地点设定
                </Title>
                <Paragraph style={{
                  fontSize: 15,
                  lineHeight: 1.8,
                  padding: 16,
                  background: token.colorBgLayout,
                  borderRadius: 8,
                  borderLeft: `4px solid ${token.colorSuccess}`
                }}>
                  {currentProject.world_location}
                </Paragraph>
              </div>
            )}

            {currentProject.world_atmosphere && (
              <div style={{ marginBottom: 24 }}>
                <Title level={5} style={{ color: token.colorWarning, marginBottom: 12 }}>
                  氛围设定
                </Title>
                <Paragraph style={{
                  fontSize: 15,
                  lineHeight: 1.8,
                  padding: 16,
                  background: token.colorBgLayout,
                  borderRadius: 8,
                  borderLeft: `4px solid ${token.colorWarning}`
                }}>
                  {currentProject.world_atmosphere}
                </Paragraph>
              </div>
            )}

            {currentProject.world_rules && (
              <div style={{ marginBottom: 0 }}>
                <Title level={5} style={{ color: token.colorError, marginBottom: 12 }}>
                  规则设定
                </Title>
                <Paragraph style={{
                  fontSize: 15,
                  lineHeight: 1.8,
                  padding: 16,
                  background: token.colorBgLayout,
                  borderRadius: 8,
                  borderLeft: `4px solid ${token.colorError}`
                }}>
                  {currentProject.world_rules}
                </Paragraph>
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* 编辑世界观模态框 */}
      <Modal
        title="编辑世界观"
        open={isEditModalVisible}
        centered
        onCancel={() => {
          setIsEditModalVisible(false);
          editForm.resetFields();
        }}
        onOk={async () => {
          try {
            const values = await editForm.validateFields();
            setIsSaving(true);

            const updatedProject = await projectApi.updateProject(currentProject.id, {
              world_time_period: values.world_time_period,
              world_location: values.world_location,
              world_atmosphere: values.world_atmosphere,
              world_rules: values.world_rules,
            });

            setCurrentProject(updatedProject);
            message.success('世界观更新成功');
            setIsEditModalVisible(false);
            editForm.resetFields();
          } catch (error) {
            console.error('更新世界观失败:', error);
            message.error('更新失败，请重试');
          } finally {
            setIsSaving(false);
          }
        }}
        confirmLoading={isSaving}
        width={800}
        okText="保存"
        cancelText="取消"
      >
        <Form
          form={editForm}
          layout="vertical"
          style={{ marginTop: 16 }}
        >
          <Form.Item
            label="时间设定"
            name="world_time_period"
            rules={[{ required: true, message: '请输入时间设定' }]}
          >
            <TextArea
              rows={4}
              placeholder="描述故事发生的时代背景..."
              showCount
              maxLength={1000}
            />
          </Form.Item>

          <Form.Item
            label="地点设定"
            name="world_location"
            rules={[{ required: true, message: '请输入地点设定' }]}
          >
            <TextArea
              rows={4}
              placeholder="描述故事发生的地理位置和环境..."
              showCount
              maxLength={1000}
            />
          </Form.Item>

          <Form.Item
            label="氛围设定"
            name="world_atmosphere"
            rules={[{ required: true, message: '请输入氛围设定' }]}
          >
            <TextArea
              rows={4}
              placeholder="描述故事的整体氛围和基调..."
              showCount
              maxLength={1000}
            />
          </Form.Item>

          <Form.Item
            label="规则设定"
            name="world_rules"
            rules={[{ required: true, message: '请输入规则设定' }]}
          >
            <TextArea
              rows={4}
              placeholder="描述这个世界的特殊规则和设定..."
              showCount
              maxLength={1000}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑项目基础信息模态框 */}
      <Modal
        title="编辑项目基础信息"
        open={isEditProjectModalVisible}
        centered
        onCancel={() => {
          setIsEditProjectModalVisible(false);
          editProjectForm.resetFields();
        }}
        onOk={async () => {
          try {
            const values = await editProjectForm.validateFields();
            setIsSavingProject(true);

            const updatedProject = await projectApi.updateProject(currentProject.id, {
              title: values.title,
              description: values.description,
              theme: values.theme,
              genre: values.genre,
              narrative_perspective: values.narrative_perspective,
              target_words: values.target_words,
            });

            setCurrentProject(updatedProject);
            message.success('项目基础信息更新成功');
            setIsEditProjectModalVisible(false);
            editProjectForm.resetFields();
          } catch (error) {
            console.error('更新项目基础信息失败:', error);
            message.error('更新失败，请重试');
          } finally {
            setIsSavingProject(false);
          }
        }}
        confirmLoading={isSavingProject}
        width={800}
        okText="保存"
        cancelText="取消"
      >
        <Form
          form={editProjectForm}
          layout="vertical"
          style={{ marginTop: 16 }}
        >
          <Form.Item
            label="小说名称"
            name="title"
            rules={[
              { required: true, message: '请输入小说名称' },
              { max: 200, message: '名称不能超过200字' }
            ]}
          >
            <Input
              placeholder="请输入小说名称"
              showCount
              maxLength={200}
            />
          </Form.Item>

          <Form.Item
            label="小说简介"
            name="description"
            rules={[
              { max: 1000, message: '简介不能超过1000字' }
            ]}
          >
            <PolishableWorldTextArea
              form={editProjectForm}
              modalApi={modal}
              projectId={currentProject?.id}
              name="description"
              label="小说简介"
              rows={4}
              placeholder="请输入小说简介（选填）"
              showCount
              maxLength={1000}
            />
          </Form.Item>

          <Form.Item
            label="小说主题"
            name="theme"
            rules={[
              { max: 500, message: '主题不能超过500字' }
            ]}
          >
            <PolishableWorldTextArea
              form={editProjectForm}
              modalApi={modal}
              projectId={currentProject?.id}
              name="theme"
              label="小说主题"
              rows={3}
              placeholder="请输入小说主题（选填）"
              showCount
              maxLength={500}
            />
          </Form.Item>

          <Form.Item
            label="小说类型"
            name="genre"
            rules={[
              { max: 100, message: '类型不能超过100字' }
            ]}
          >
            <Input
              placeholder="请输入小说类型，如：玄幻、都市、科幻等（选填）"
              showCount
              maxLength={100}
            />
          </Form.Item>

          <Form.Item
            label="叙事视角"
            name="narrative_perspective"
          >
            <Select
              placeholder="请选择叙事视角（选填）"
              allowClear
              options={[
                { label: '第一人称', value: '第一人称' },
                { label: '第三人称', value: '第三人称' },
                { label: '全知视角', value: '全知视角' }
              ]}
            />
          </Form.Item>

          <Form.Item
            label="目标字数"
            name="target_words"
            rules={[
              { type: 'number', min: 0, message: '目标字数不能为负数' },
              { type: 'number', max: 2147483647, message: '目标字数超出范围' }
            ]}
          >
            <InputNumber
              style={{ width: '100%' }}
              placeholder="请输入目标字数（选填，最大21亿字）"
              min={0}
              max={2147483647}
              step={1000}
              addonAfter="字"
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* AI重新生成加载遮罩 */}
      <SSELoadingOverlay
        loading={isRegenerating}
        progress={regenerateProgress}
        message={regenerateMessage}
      />

      {/* 预览重新生成的内容模态框 */}
      <Modal
        title="预览重新生成的世界观"
        open={isPreviewModalVisible}
        centered
        width={900}
        onOk={handleConfirmSave}
        onCancel={handleCancelSave}
        confirmLoading={isSavingPreview}
        okText="确认替换"
        cancelText="取消"
        okButtonProps={{ danger: true }}
      >
        {newWorldData && (
          <div style={{ maxHeight: '60vh', overflowY: 'auto' }}>
            <div style={{ marginBottom: 24, padding: 16, background: token.colorWarningBg, border: `1px solid ${token.colorWarningBorder}`, borderRadius: 8 }}>
              <Typography.Text type="warning" strong>
                ⚠️ 注意：点击"确认替换"将会用新内容替换当前的世界观设定
              </Typography.Text>
            </div>

            <div style={{ marginBottom: 24 }}>
              <Title level={5} style={{ color: token.colorPrimary, marginBottom: 12 }}>
                时间设定
              </Title>
              <Paragraph style={{
                fontSize: 15,
                lineHeight: 1.8,
                padding: 16,
                background: token.colorBgLayout,
                borderRadius: 8,
                borderLeft: `4px solid ${token.colorPrimary}`
              }}>
                {newWorldData.time_period}
              </Paragraph>
            </div>

            <div style={{ marginBottom: 24 }}>
              <Title level={5} style={{ color: token.colorSuccess, marginBottom: 12 }}>
                地点设定
              </Title>
              <Paragraph style={{
                fontSize: 15,
                lineHeight: 1.8,
                padding: 16,
                background: token.colorBgLayout,
                borderRadius: 8,
                borderLeft: `4px solid ${token.colorSuccess}`
              }}>
                {newWorldData.location}
              </Paragraph>
            </div>

            <div style={{ marginBottom: 24 }}>
              <Title level={5} style={{ color: token.colorWarning, marginBottom: 12 }}>
                氛围设定
              </Title>
              <Paragraph style={{
                fontSize: 15,
                lineHeight: 1.8,
                padding: 16,
                background: token.colorBgLayout,
                borderRadius: 8,
                borderLeft: `4px solid ${token.colorWarning}`
              }}>
                {newWorldData.atmosphere}
              </Paragraph>
            </div>

            <div style={{ marginBottom: 0 }}>
              <Title level={5} style={{ color: token.colorError, marginBottom: 12 }}>
                规则设定
              </Title>
              <Paragraph style={{
                fontSize: 15,
                lineHeight: 1.8,
                padding: 16,
                background: token.colorBgLayout,
                borderRadius: 8,
                borderLeft: `4px solid ${token.colorError}`
              }}>
                {newWorldData.rules}
              </Paragraph>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
