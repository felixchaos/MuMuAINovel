import { useState, useEffect } from 'react';
import {
  Card,
  Tabs,
  Button,
  Switch,
  Modal,
  Input,
  Tag,
  message,
  Space,
  Typography,
  Row,
  Col,
  Alert,
  Upload,
  Spin,
  Empty,
  theme
} from 'antd';
import {
  EditOutlined,
  ReloadOutlined,
  DownloadOutlined,
  UploadOutlined,
  CheckCircleOutlined,
  FileSearchOutlined,
  InfoCircleOutlined
} from '@ant-design/icons';
import axios from 'axios';
import { promptTemplateCardStyles, promptTemplateCardHoverHandlers, promptTemplateGridConfig } from '../components/CardStyles';

const { TextArea } = Input;
const { Title, Text, Paragraph } = Typography;

interface PromptTemplate {
  id: string;
  template_key: string;
  template_name: string;
  template_content: string;
  description: string;
  category: string;
  parameters: string;
  is_active: boolean;
  is_system_default: boolean;
  created_at: string;
  updated_at: string;
}

interface CategoryGroup {
  category: string;
  count: number;
  templates: PromptTemplate[];
}

export default function PromptTemplates() {
  const { token } = theme.useToken();
  const [modal, contextHolder] = Modal.useModal();
  const [categories, setCategories] = useState<CategoryGroup[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>('0');
  const [editingTemplate, setEditingTemplate] = useState<PromptTemplate | null>(null);
  const [editorVisible, setEditorVisible] = useState(false);
  const [loading, setLoading] = useState(false);

  const isMobile = window.innerWidth <= 768;

  // 加载模板数据
  const loadTemplates = async () => {
    try {
      setLoading(true);
      const response = await axios.get<CategoryGroup[]>('/api/prompt-templates/categories');
      setCategories(response.data);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTemplates();
  }, []);

  // 获取当前分类的模板
  const getCurrentTemplates = (): PromptTemplate[] => {
    const index = parseInt(selectedCategory);
    if (index === 0) {
      return categories.flatMap(cat => cat.templates);
    }
    return categories[index - 1]?.templates || [];
  };

  // 编辑模板
  const handleEdit = (template: PromptTemplate) => {
    setEditingTemplate({ ...template });
    setEditorVisible(true);
  };

  // 保存模板
  const handleSave = async () => {
    if (!editingTemplate) return;

    try {
      setLoading(true);
      const createsAccountCopy = editingTemplate.is_system_default;
      await axios.post('/api/prompt-templates', {
        template_key: editingTemplate.template_key,
        template_name: editingTemplate.template_name,
        template_content: editingTemplate.template_content,
        description: editingTemplate.description,
        category: editingTemplate.category,
        parameters: editingTemplate.parameters,
        is_active: editingTemplate.is_active
      });
      message.success(createsAccountCopy ? '已保存为当前账户的自定义副本' : '保存成功');
      setEditorVisible(false);
      loadTemplates();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '保存失败');
    } finally {
      setLoading(false);
    }
  };

  // 重置为系统默认
  const handleReset = async (templateKey: string) => {
    modal.confirm({
      title: '确认重置',
      content: '确定要删除当前账户的自定义副本并恢复系统默认吗？这不会影响其他账户。',
      okText: '确定',
      cancelText: '取消',
      centered: true,
      onOk: async () => {
        try {
          setLoading(true);
          await axios.post(`/api/prompt-templates/${templateKey}/reset`);
          message.success('已重置为系统默认');
          loadTemplates();
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string } } };
          message.error(err.response?.data?.detail || '重置失败');
        } finally {
          setLoading(false);
        }
      }
    });
  };

  // 切换启用状态
  const handleToggleActive = async (template: PromptTemplate, checked: boolean) => {
    try {
      await axios.put(`/api/prompt-templates/${template.template_key}`, {
        is_active: checked
      });
      loadTemplates();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '操作失败');
    }
  };

  // 导出所有模板
  const handleExport = async () => {
    try {
      const response = await axios.post('/api/prompt-templates/export');
      const stats = response.data.statistics;
      
      const blob = new Blob([JSON.stringify(response.data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `prompt-templates-${new Date().toISOString().split('T')[0]}.json`;
      a.click();
      URL.revokeObjectURL(url);
      
      if (stats) {
        message.success(
          `成功导出 ${stats.total} 个提示词配置（${stats.customized} 个自定义，${stats.system_default} 个系统默认）`,
          5
        );
      } else {
        message.success('导出成功');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '导出失败');
    }
  };

  // 导入模板
  const handleImport = async (file: File) => {
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const response = await axios.post('/api/prompt-templates/import', data);
      
      const result = response.data;
      const stats = result.statistics;
      
      // 构建详细的成功消息
      let successMsg = `导入成功！\n`;
      if (stats) {
        successMsg += `• 保持系统默认：${stats.kept_system_default} 个\n`;
        successMsg += `• 创建/更新自定义：${stats.created_or_updated} 个`;
        
        if (stats.converted_to_custom > 0) {
          successMsg += `\n• 检测到修改（已转为自定义）：${stats.converted_to_custom} 个`;
        }
      }
      
      // 如果有被转换的模板，显示详细信息
      if (result.converted_templates && result.converted_templates.length > 0) {
        modal.info({
          title: '导入完成',
          width: 600,
          centered: true,
          content: (
            <div>
              <p style={{ marginBottom: 16 }}>{successMsg}</p>
              {result.converted_templates.length > 0 && (
                <div>
                  <p style={{ fontWeight: 'bold', marginBottom: 8 }}>以下模板内容与系统默认不一致，已转为自定义：</p>
                  <ul style={{ marginLeft: 20 }}>
                    {result.converted_templates.map((t: { template_key: string; template_name: string }) => (
                      <li key={t.template_key}>
                        {t.template_name} ({t.template_key})
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ),
          okText: '确定'
        });
      } else {
        message.success(successMsg, 5);
      }
      
      loadTemplates();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '导入失败');
    }
    return false; // 阻止默认上传行为
  };

  const currentTemplates = getCurrentTemplates();
  const pageBackground = `linear-gradient(180deg, ${token.colorBgLayout} 0%, ${token.colorFillSecondary} 100%)`;
  const headerBackground = `linear-gradient(135deg, ${token.colorPrimary} 0%, ${token.colorPrimaryHover} 100%)`;

  return (
    <>
      {contextHolder}
      <div style={{
      minHeight: '90vh',
      background: pageBackground,
      padding: isMobile ? '20px 16px 70px' : '24px 24px 70px',
      display: 'flex',
      flexDirection: 'column',
    }}>
      <div style={{
        maxWidth: 1400,
        margin: '0 auto',
        width: '100%',
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
      }}>
        {/* 顶部导航卡片 */}
        <Card
          variant="borderless"
          style={{
            background: headerBackground,
            borderRadius: isMobile ? 16 : 24,
            boxShadow: token.boxShadowSecondary,
            marginBottom: isMobile ? 20 : 24,
            border: 'none',
            position: 'relative',
            overflow: 'hidden'
          }}
        >
          {/* 装饰性背景元素 */}
          <div style={{ position: 'absolute', top: -60, right: -60, width: 200, height: 200, borderRadius: '50%', background: token.colorWhite, opacity: 0.08, pointerEvents: 'none' }} />
          <div style={{ position: 'absolute', bottom: -40, left: '30%', width: 120, height: 120, borderRadius: '50%', background: token.colorWhite, opacity: 0.05, pointerEvents: 'none' }} />
          <div style={{ position: 'absolute', top: '50%', right: '15%', width: 80, height: 80, borderRadius: '50%', background: token.colorWhite, opacity: 0.06, pointerEvents: 'none' }} />

          <Row align="middle" justify="space-between" gutter={[16, 16]} style={{ position: 'relative', zIndex: 1 }}>
            <Col xs={24} sm={12} md={14}>
              <Space direction="vertical" size={4}>
                <Title level={isMobile ? 3 : 2} style={{ margin: 0, color: token.colorWhite, textShadow: `0 2px 4px ${token.colorBgMask}` }}>
                  <FileSearchOutlined style={{ color: token.colorWhite, opacity: 0.9, marginRight: 8 }} />
                  提示词模板管理
                </Title>
                <Text style={{ fontSize: isMobile ? 12 : 14, color: token.colorTextLightSolid, opacity: 0.85, marginLeft: isMobile ? 40 : 48 }}>
                  按账户隔离自定义AI生成提示词
                </Text>
              </Space>
            </Col>
            <Col xs={24} sm={12} md={10}>
              <Space wrap style={{ justifyContent: isMobile ? 'flex-start' : 'flex-end', width: '100%' }}>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={handleExport}
                  size={isMobile ? 'small' : 'middle'}
                  style={{
                    borderRadius: 12,
                    background: token.colorWhite,
                    border: `1px solid ${token.colorWhite}`,
                    boxShadow: token.boxShadow,
                    color: token.colorPrimary,
                    fontWeight: 600,
                    backdropFilter: 'blur(10px)',
                    transition: 'all 0.3s ease'
                  }}
                >
                  导出配置
                </Button>
                <Upload
                  accept=".json"
                  showUploadList={false}
                  beforeUpload={handleImport}
                >
                  <Button
                    icon={<UploadOutlined />}
                    size={isMobile ? 'small' : 'middle'}
                    style={{
                      borderRadius: 12,
                      background: token.colorWhite,
                      border: `1px solid ${token.colorWhite}`,
                      boxShadow: token.boxShadow,
                      color: token.colorPrimary,
                      fontWeight: 600,
                      backdropFilter: 'blur(10px)',
                    }}
                  >
                    导入配置
                  </Button>
                </Upload>
              </Space>
            </Col>
          </Row>

          {/* 使用提示 */}
          <Alert
            message={
              <Space align="center">
                <InfoCircleOutlined style={{ fontSize: 16, color: token.colorPrimary }} />
                <Text strong style={{ fontSize: isMobile ? 13 : 14 }}>使用说明</Text>
              </Space>
            }
            description={
              <div>
                <Text style={{ fontSize: isMobile ? 12 : 13, display: 'block', marginBottom: 8 }}>
                  • <strong>系统默认模板</strong>（灰色头部）：始终启用，无需手动开关。点击"编辑"后将创建仅当前账户生效的自定义副本。
                </Text>
                <Text style={{ fontSize: isMobile ? 12 : 13, display: 'block' }}>
                  • <strong>已自定义模板</strong>（紫色头部）：仅当前账户生效，可通过开关控制启用/禁用，使用 <Text code>{'{variable_name}'}</Text> 格式表示变量占位符。点击"重置"可恢复为系统默认。
                </Text>
              </div>
            }
            type="info"
            showIcon={false}
            style={{
              marginTop: isMobile ? 16 : 24,
              borderRadius: 12,
              background: token.colorInfoBg,
              border: `1px solid ${token.colorInfoBorder}`
            }}
          />
        </Card>

        {/* 主内容区 */}
        <div style={{ flex: 1 }}>
          <Spin spinning={loading}>
            {/* 分类标签 */}
            {categories.length > 0 && (
              <Card
                variant="borderless"
                style={{
                  background: token.colorBgContainer,
                  borderRadius: isMobile ? 12 : 16,
                  boxShadow: token.boxShadowSecondary,
                  marginBottom: isMobile ? 16 : 24
                }}
                styles={{ body: { padding: isMobile ? '12px' : '16px' } }}
              >
                <Tabs
                  activeKey={selectedCategory}
                  onChange={setSelectedCategory}
                  items={[
                    { key: '0', label: `全部 (${categories.reduce((sum, cat) => sum + cat.count, 0)})` },
                    ...categories.map((cat, index) => ({
                      key: (index + 1).toString(),
                      label: `${cat.category} (${cat.count})`
                    }))
                  ]}
                />
              </Card>
            )}

            {/* 模板列表 */}
            {currentTemplates.length === 0 ? (
              <Card
                variant="borderless"
                style={{
                  background: token.colorBgContainer,
                  borderRadius: isMobile ? 12 : 16,
                  boxShadow: token.boxShadowSecondary,
                }}
              >
                <Empty
                  description="暂无模板数据"
                  style={{ padding: '80px 0' }}
                />
              </Card>
            ) : (
              <Row gutter={[16, 16]}>
                {currentTemplates.map(template => (
                  <Col {...promptTemplateGridConfig} key={template.id}>
                    <Card
                      hoverable
                      variant="borderless"
                      style={promptTemplateCardStyles.templateCard}
                      styles={{ body: { padding: 0, overflow: 'hidden' } }}
                      {...promptTemplateCardHoverHandlers}
                    >
                      {/* 头部 */}
                      <div style={{
                        background: template.is_system_default
                          ? token.colorFillTertiary
                          : token.colorPrimary,
                        padding: isMobile ? '16px' : '20px',
                        position: 'relative'
                      }}>
                        <Space direction="vertical" size={8} style={{ width: '100%' }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <Title level={isMobile ? 5 : 4} style={{ margin: 0, color: template.is_system_default ? token.colorText : token.colorWhite, flex: 1 }} ellipsis>
                              {template.template_name}
                            </Title>
                            {!template.is_system_default && (
                              <Switch
                                checked={template.is_active}
                                onChange={(checked) => handleToggleActive(template, checked)}
                                size={isMobile ? 'small' : 'default'}
                                style={{ marginLeft: 8 }}
                              />
                            )}
                          </div>
                          <Space wrap>
                            <Tag color={template.is_system_default ? 'default' : 'rgba(255,255,255,0.3)'} style={{ color: template.is_system_default ? token.colorTextSecondary : token.colorWhite, border: 'none' }}>
                              {template.category}
                            </Tag>
                            <Tag color={template.is_system_default ? 'default' : 'rgba(255,255,255,0.3)'} style={{ color: template.is_system_default ? token.colorTextSecondary : token.colorWhite, border: 'none' }}>
                              {template.is_system_default ? '系统默认' : '已自定义'}
                            </Tag>
                          </Space>
                        </Space>
                      </div>

                      {/* 内容 */}
                      <div style={{ padding: isMobile ? '16px' : '20px' }}>
                        <Paragraph
                          type="secondary"
                          ellipsis={{ rows: 3 }}
                          style={{ minHeight: 66, marginBottom: 16 }}
                        >
                          {template.description || '暂无描述'}
                        </Paragraph>

                        <Space wrap style={{ marginBottom: 16 }}>
                          <Tag
                            icon={<CheckCircleOutlined />}
                            color={template.is_system_default || template.is_active ? 'success' : 'default'}
                          >
                            {template.is_system_default ? '始终启用' : (template.is_active ? '已启用' : '已禁用')}
                          </Tag>
                        </Space>

                        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 16 }}>
                          模板键: {template.template_key}
                        </Text>

                        {/* 操作按钮 */}
                        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                          <Button
                            type="primary"
                            icon={<EditOutlined />}
                            onClick={() => handleEdit(template)}
                            size={isMobile ? 'small' : 'middle'}
                            style={{ borderRadius: 6 }}
                          >
                            编辑
                          </Button>
                          <Button
                            icon={<ReloadOutlined />}
                            onClick={() => handleReset(template.template_key)}
                            size={isMobile ? 'small' : 'middle'}
                            style={{ borderRadius: 6 }}
                          >
                            重置
                          </Button>
                        </Space>
                      </div>
                    </Card>
                  </Col>
                ))}
              </Row>
            )}
          </Spin>
        </div>
      </div>

      {/* 编辑对话框 */}
      <Modal
        title={`编辑模板: ${editingTemplate?.template_name}`}
        open={editorVisible}
        onCancel={() => setEditorVisible(false)}
        onOk={handleSave}
        width={isMobile ? '100%' : 900}
        centered={!isMobile}
        confirmLoading={loading}
        okText="保存"
        cancelText="取消"
        style={isMobile ? { top: 0, paddingBottom: 0, maxWidth: '100vw' } : undefined}
        styles={isMobile ? {
          body: {
            maxHeight: 'calc(100vh - 110px)',
            overflowY: 'auto',
            padding: '16px'
          }
        } : undefined}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: 500 }}>模板名称</label>
            <Input
              value={editingTemplate?.template_name || ''}
              onChange={(e) => setEditingTemplate(prev => prev ? { ...prev, template_name: e.target.value } : null)}
              placeholder="输入模板名称"
            />
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: 500 }}>描述</label>
            <TextArea
              value={editingTemplate?.description || ''}
              onChange={(e) => setEditingTemplate(prev => prev ? { ...prev, description: e.target.value } : null)}
              rows={2}
              placeholder="简要描述模板用途"
            />
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: 500 }}>模板内容</label>
            <TextArea
              value={editingTemplate?.template_content || ''}
              onChange={(e) => setEditingTemplate(prev => prev ? { ...prev, template_content: e.target.value } : null)}
              rows={isMobile ? 15 : 20}
              style={{ fontFamily: 'monospace', fontSize: '13px' }}
              placeholder="输入提示词模板内容..."
            />
          </div>

          <Alert
            message="提示：使用 {variable_name} 格式表示变量占位符"
            type="info"
            showIcon
            style={{ borderRadius: 8 }}
          />
        </Space>
      </Modal>
    </div>
    </>
  );
}
