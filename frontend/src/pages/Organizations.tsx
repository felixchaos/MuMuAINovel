import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { Card, Table, Tag, Button, Space, message, Modal, Form, Select, InputNumber, Input, Descriptions, Drawer, theme } from 'antd';
import { PlusOutlined, UserOutlined, EditOutlined, DeleteOutlined, UnorderedListOutlined, BankOutlined, ThunderboltOutlined, HighlightOutlined, ReloadOutlined } from '@ant-design/icons';
import { useStore } from '../store';
import { useCharacterSync } from '../store/hooks';
import { characterApi, polishApi } from '../services/api';
import { SSEPostClient } from '../utils/sseClient';
import { SSELoadingOverlay } from '../components/SSELoadingOverlay';
import { extractJsonObject } from '../utils/jsonExtract';
import axios from 'axios';

const { TextArea } = Input;

interface Organization {
  id: string;
  character_id: string;
  name: string;
  type: string;
  purpose: string;
  member_count: number;
  power_level: number;
  location?: string;
  motto?: string;
  color?: string;
}

interface OrganizationMember {
  id: string;
  character_id: string;
  character_name: string;
  position: string;
  rank: number;
  loyalty: number;
  contribution: number;
  status: string;
  joined_at?: string;
  left_at?: string;
  notes?: string;
}

interface Character {
  id: string;
  name: string;
  is_organization: boolean;
}

interface OrganizationFormValues {
  name: string;
  organization_type?: string;
  organization_purpose?: string;
  background?: string;
  power_level?: number;
  location?: string;
  motto?: string;
  color?: string;
}

interface OrganizationGenerateValues {
  name?: string;
  organization_type?: string;
  background?: string;
  requirements?: string;
}

const getStringField = (data: Record<string, unknown> | null, key: string): string | undefined => {
  const value = data?.[key];
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
};

const getNumberField = (data: Record<string, unknown> | null, key: string): number | undefined => {
  const value = data?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
};

export default function Organizations() {
  const { projectId } = useParams<{ projectId: string }>();
  const { currentProject } = useStore();
  const { refreshCharacters } = useCharacterSync();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selectedOrg, setSelectedOrg] = useState<Organization | null>(null);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(false);
  const [isAddMemberModalOpen, setIsAddMemberModalOpen] = useState(false);
  const [isEditMemberModalOpen, setIsEditMemberModalOpen] = useState(false);
  const [isEditOrgModalOpen, setIsEditOrgModalOpen] = useState(false);
  const [isCreateOrgModalOpen, setIsCreateOrgModalOpen] = useState(false);
  const [editingMember, setEditingMember] = useState<OrganizationMember | null>(null);
  const [isGeneratingOrg, setIsGeneratingOrg] = useState(false);
  const [isOptimizingOrg, setIsOptimizingOrg] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const [form] = Form.useForm();
  const [createOrgForm] = Form.useForm<OrganizationFormValues>();
  const [generateOrgForm] = Form.useForm<OrganizationGenerateValues>();
  const [editMemberForm] = Form.useForm();
  const [editOrgForm] = Form.useForm();
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const [modal, contextHolder] = Modal.useModal();
  const [orgListVisible, setOrgListVisible] = useState(false);
  const { token } = theme.useToken();

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const loadOrganizations = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`/api/organizations/project/${projectId}`);
      setOrganizations(res.data);
      if (res.data.length > 0 && !selectedOrg) {
        setSelectedOrg(res.data[0]);
        loadMembers(res.data[0].id);
      }
    } catch (error) {
      message.error('加载组织列表失败');
      console.error(error);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const loadCharacters = useCallback(async () => {
    try {
      const res = await axios.get(`/api/characters?project_id=${projectId}`);
      setCharacters(res.data.items || []);
    } catch (error) {
      console.error('加载角色列表失败', error);
    }
  }, [projectId]);

  useEffect(() => {
    if (projectId) {
      loadOrganizations();
      loadCharacters();
    }
  }, [projectId, loadOrganizations, loadCharacters]);

  const loadMembers = async (orgId: string) => {
    try {
      const res = await axios.get(`/api/organizations/${orgId}/members`);
      setMembers(res.data);
    } catch (error) {
      message.error('加载成员列表失败');
      console.error(error);
    }
  };

  const handleSelectOrganization = (org: Organization) => {
    setSelectedOrg(org);
    loadMembers(org.id);
  };

  const handleCreateOrganization = async (values: OrganizationFormValues) => {
    if (!projectId) return;

    try {
      await characterApi.createCharacter({
        project_id: projectId,
        name: values.name,
        is_organization: true,
        role_type: 'supporting',
        organization_type: values.organization_type,
        organization_purpose: values.organization_purpose,
        background: values.background,
        power_level: values.power_level ?? 50,
        location: values.location,
        motto: values.motto,
        color: values.color,
      });
      message.success('组织创建成功');
      setIsCreateOrgModalOpen(false);
      createOrgForm.resetFields();
      await refreshCharacters();
      await loadOrganizations();
    } catch (error) {
      message.error('创建组织失败');
      console.error(error);
    }
  };

  const handleGenerateOrganization = async (values: OrganizationGenerateValues) => {
    if (!projectId) return;

    try {
      setIsGeneratingOrg(true);
      setProgress(0);
      setProgressMessage('准备生成组织...');

      const client = new SSEPostClient(
        '/api/organizations/generate-stream',
        {
          project_id: projectId,
          name: values.name,
          organization_type: values.organization_type,
          background: values.background,
          requirements: values.requirements,
        },
        {
          onProgress: (msg, prog) => {
            setProgress(prog);
            setProgressMessage(msg);
          },
          onError: (error) => {
            message.error(`生成失败: ${error}`);
          },
          onComplete: () => {
            setProgress(100);
            setProgressMessage('生成完成！');
          },
        }
      );

      await client.connect();
      message.success('AI生成组织成功');
      Modal.destroyAll();
      generateOrgForm.resetFields();
      await refreshCharacters();
      await loadOrganizations();
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'AI生成组织失败');
    } finally {
      setTimeout(() => {
        setIsGeneratingOrg(false);
        setProgress(0);
        setProgressMessage('');
      }, 500);
    }
  };

  const handleOptimizeOrganization = async () => {
    if (!selectedOrg) return;

    try {
      setIsOptimizingOrg(true);
      const character = await characterApi.getCharacter(selectedOrg.character_id);
      const source = JSON.stringify({
        type: 'organization',
        name: selectedOrg.name,
        organization_type: selectedOrg.type || '',
        organization_purpose: selectedOrg.purpose || '',
        power_level: selectedOrg.power_level,
        location: selectedOrg.location || '',
        motto: selectedOrg.motto || '',
        color: selectedOrg.color || '',
        background: character.background || '',
      }, null, 2);
      const result = await polishApi.polishText({
        original_text: source,
        instruction: [
          '你是小说设定编辑，请分析并优化组织/势力设定。',
          '只优化表达、层次和可读性，不改变既有事实、名称、阵营、世界观和时间线。',
          '严格只输出 JSON，不要 Markdown，不要解释。',
          'JSON 字段：organization_purpose、motto、background、location、color、power_level。'
        ].join('\n'),
        temperature: 0.6,
      });
      const parsed = extractJsonObject(result.polished_text || '');
      const updateData = {
        organization_purpose: getStringField(parsed, 'organization_purpose'),
        motto: getStringField(parsed, 'motto'),
        background: getStringField(parsed, 'background'),
        location: getStringField(parsed, 'location'),
        color: getStringField(parsed, 'color'),
        power_level: getNumberField(parsed, 'power_level'),
      };
      const filtered = Object.fromEntries(
        Object.entries(updateData).filter(([, value]) => value !== undefined)
      );

      if (Object.keys(filtered).length === 0) {
        message.warning('AI返回格式无法识别');
        return;
      }

      await characterApi.updateCharacter(selectedOrg.character_id, filtered);
      message.success('组织设定已优化');
      await refreshCharacters();
      await loadOrganizations();
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'AI优化组织失败');
    } finally {
      setIsOptimizingOrg(false);
    }
  };

  const handleAddMember = async (values: Record<string, unknown>) => {
    if (!selectedOrg) return;

    try {
      await axios.post(`/api/organizations/${selectedOrg.id}/members`, values);
      message.success('成员添加成功');
      setIsAddMemberModalOpen(false);
      form.resetFields();
      loadMembers(selectedOrg.id);
      loadOrganizations(); // 刷新成员计数
    } catch (error) {
      message.error('添加成员失败');
      console.error(error);
    }
  };

  const handleRemoveMember = async (memberId: string) => {
    modal.confirm({
      title: '确认移除',
      content: '确定要移除该成员吗？',
      centered: true,
      okText: '移除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await axios.delete(`/api/organizations/members/${memberId}`);
          message.success('成员移除成功');
          if (selectedOrg) {
            loadMembers(selectedOrg.id);
            loadOrganizations(); // 刷新成员计数
          }
        } catch (error) {
          message.error('移除失败');
          console.error(error);
        }
      }
    });
  };

  const handleEditMember = (member: OrganizationMember) => {
    setEditingMember(member);
    editMemberForm.setFieldsValue({
      position: member.position,
      rank: member.rank,
      loyalty: member.loyalty,
      contribution: member.contribution,
      status: member.status,
      notes: member.notes,
      joined_at: member.joined_at
    });
    setIsEditMemberModalOpen(true);
  };

  const handleUpdateMember = async (values: Record<string, unknown>) => {
    if (!editingMember) return;

    try {
      await axios.put(`/api/organizations/members/${editingMember.id}`, values);
      message.success('成员信息更新成功');
      setIsEditMemberModalOpen(false);
      editMemberForm.resetFields();
      setEditingMember(null);
      if (selectedOrg) {
        loadMembers(selectedOrg.id);
      }
    } catch (error) {
      message.error('更新失败');
      console.error(error);
    }
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      active: 'green',
      retired: 'default',
      expelled: 'red',
      deceased: 'black'
    };
    return colors[status] || 'default';
  };

  const getStatusText = (status: string) => {
    const texts: Record<string, string> = {
      active: '在职',
      retired: '退休',
      expelled: '除名',
      deceased: '已故'
    };
    return texts[status] || status;
  };

  const memberColumns = [
    {
      title: '姓名',
      dataIndex: 'character_name',
      key: 'name',
      render: (name: string) => (
        <Space>
          <UserOutlined />
          <span>{name}</span>
        </Space>
      ),
      width: isMobile ? 100 : undefined,
    },
    {
      title: '职位',
      dataIndex: 'position',
      key: 'position',
      render: (position: string, record: OrganizationMember) => (
        <Tag color="blue">{position} {!isMobile && `(级别 ${record.rank})`}</Tag>
      ),
      width: isMobile ? 120 : undefined,
    },
    {
      title: '忠诚度',
      dataIndex: 'loyalty',
      key: 'loyalty',
      render: (loyalty: number) => (
        <span style={{ color: loyalty >= 70 ? 'green' : loyalty >= 40 ? 'orange' : 'red' }}>
          {loyalty}%
        </span>
      ),
      width: isMobile ? 80 : undefined,
    },
    {
      title: '贡献度',
      dataIndex: 'contribution',
      key: 'contribution',
      render: (contribution: number) => `${contribution}%`,
      width: isMobile ? 80 : undefined,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>{getStatusText(status)}</Tag>
      ),
      width: isMobile ? 80 : undefined,
    },
    {
      title: '加入时间',
      dataIndex: 'joined_at',
      key: 'joined_at',
      render: (time: string) => time || '-',
      width: isMobile ? 120 : undefined,
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: OrganizationMember) => (
        <Space size={isMobile ? 0 : 'small'}>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEditMember(record)}
            style={isMobile ? { padding: '4px' } : undefined}
          >
            {isMobile ? '' : '编辑'}
          </Button>
          <Button
            type="link"
            danger
            size="small"
            icon={<DeleteOutlined />}
            onClick={() => handleRemoveMember(record.id)}
            style={isMobile ? { padding: '4px' } : undefined}
          >
            {isMobile ? '' : '移除'}
          </Button>
        </Space>
      ),
      width: isMobile ? 50 : undefined,
      fixed: isMobile ? 'right' as const : undefined,
    },
  ];

  // 过滤掉已是成员的角色
  const availableCharacters = characters.filter(
    c => !c.is_organization && !members.some(m => m.character_id === c.id)
  );

  const renderToolbar = () => (
    <Space wrap size={isMobile ? 8 : 'middle'}>
      {isMobile && organizations.length > 0 && (
        <Button
          icon={<UnorderedListOutlined />}
          onClick={() => setOrgListVisible(true)}
        >
          组织列表
        </Button>
      )}
      <Button
        type="primary"
        icon={<PlusOutlined />}
        onClick={() => {
          createOrgForm.setFieldsValue({ power_level: 50 });
          setIsCreateOrgModalOpen(true);
        }}
      >
        手动添加
      </Button>
      <Button
        type="dashed"
        icon={<ThunderboltOutlined />}
        loading={isGeneratingOrg}
        onClick={() => {
          generateOrgForm.resetFields();
          modal.confirm({
            title: 'AI分析大纲/章节生成组织',
            width: 600,
            centered: true,
            content: (
              <Form form={generateOrgForm} layout="vertical" style={{ marginTop: 16 }}>
                <Form.Item label="组织名称" name="name">
                  <Input placeholder="可选，留空则由 AI 根据已有大纲和章节生成" />
                </Form.Item>
                <Form.Item label="组织类型" name="organization_type">
                  <Input placeholder="如：军方、公司、学院、秘密结社" />
                </Form.Item>
                <Form.Item label="背景设定" name="background">
                  <TextArea rows={3} placeholder="简要描述组织背景和环境" />
                </Form.Item>
                <Form.Item label="其他要求" name="requirements">
                  <TextArea rows={2} placeholder="其他特殊要求" />
                </Form.Item>
              </Form>
            ),
            okText: '生成',
            cancelText: '取消',
            onOk: async () => {
              const values = await generateOrgForm.validateFields();
              await handleGenerateOrganization(values);
            },
          });
        }}
      >
        AI分析生成组织
      </Button>
      <Button
        icon={<ReloadOutlined />}
        onClick={() => {
          loadOrganizations();
          loadCharacters();
        }}
      >
        刷新
      </Button>
    </Space>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {contextHolder}
      
      {/* 页面标题 - 仅桌面端显示 */}
      {!isMobile && (
        <div style={{
          padding: '16px 0',
          marginBottom: 16,
          borderBottom: `1px solid ${token.colorBorderSecondary}`
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16 }}>
            <h2 style={{ margin: 0, fontSize: 24 }}>
              <BankOutlined style={{ marginRight: 8 }} />
              组织管理
            </h2>
            {renderToolbar()}
          </div>
        </div>
      )}

      {isMobile && (
        <Card size="small" style={{ marginBottom: 8 }}>
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Space>
              <BankOutlined />
              <span style={{ fontSize: 16, fontWeight: 600 }}>组织管理</span>
              <Tag color="blue">{currentProject?.title}</Tag>
            </Space>
            {renderToolbar()}
          </Space>
        </Card>
      )}
      
      <div style={{
        flex: 1,
        display: 'flex',
        gap: isMobile ? 0 : 16,
        flexDirection: isMobile ? 'column' : 'row',
        overflow: 'hidden'
      }}>
        {/* 左侧组织列表 - 桌面端 */}
        {!isMobile && (
        <Card
          title={`组织列表 (${organizations.length})`}
          style={{ width: 300, height: '100%', overflow: 'hidden' }}
          bodyStyle={{ padding: 0, height: 'calc(100% - 57px)', overflow: 'auto' }}
          loading={loading}
        >
          {organizations.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px 20px', color: token.colorTextTertiary }}>
              暂无组织
            </div>
          ) : (
            <Space direction="vertical" style={{ width: '100%', padding: '12px' }}>
              {organizations.map(org => (
                <Card
                  key={org.id}
                  size="small"
                  hoverable
                  style={{
                    cursor: 'pointer',
                    border: selectedOrg?.id === org.id ? `2px solid ${token.colorPrimary}` : `1px solid ${token.colorBorder}`,
                    background: selectedOrg?.id === org.id ? token.colorPrimaryBg : 'transparent'
                  }}
                  onClick={() => handleSelectOrganization(org)}
                >
                  <Space direction="vertical" size="small" style={{ width: '100%' }}>
                    <strong style={{ fontSize: 14 }}>{org.name}</strong>
                    <Tag color="blue">{org.type}</Tag>
                    <div style={{ fontSize: '12px', color: token.colorTextSecondary }}>
                      成员: {org.member_count} | 势力: {org.power_level}
                    </div>
                  </Space>
                </Card>
              ))}
            </Space>
          )}
        </Card>
        )}

        {/* 移动端组织列表抽屉 */}
      {isMobile && (
        <Drawer
          title="组织列表"
          placement="left"
          onClose={() => setOrgListVisible(false)}
          open={orgListVisible}
          width="85%"
          styles={{ body: { padding: 0 } }}
        >
          {organizations.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px 20px', color: token.colorTextTertiary }}>
              暂无组织
            </div>
          ) : (
            <Space direction="vertical" style={{ width: '100%', padding: '12px' }}>
              {organizations.map(org => (
                <Card
                  key={org.id}
                  size="small"
                  hoverable
                  style={{
                    cursor: 'pointer',
                    border: selectedOrg?.id === org.id ? `2px solid ${token.colorPrimary}` : `1px solid ${token.colorBorder}`,
                    background: selectedOrg?.id === org.id ? token.colorPrimaryBg : 'transparent'
                  }}
                  onClick={() => {
                    handleSelectOrganization(org);
                    setOrgListVisible(false);
                  }}
                >
                  <Space direction="vertical" size="small" style={{ width: '100%' }}>
                    <strong style={{ fontSize: 14 }}>{org.name}</strong>
                    <Tag color="blue">{org.type}</Tag>
                    <div style={{ fontSize: '12px', color: token.colorTextSecondary }}>
                      成员: {org.member_count} | 势力: {org.power_level}
                    </div>
                  </Space>
                </Card>
              ))}
            </Space>
          )}
        </Drawer>
        )}

        {/* 右侧内容区域 */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        {!selectedOrg ? (
          <Card style={{ height: '100%' }}>
            <div style={{ textAlign: 'center', padding: '100px 20px', color: token.colorTextTertiary }}>
              <div>请选择一个组织查看详情</div>
            </div>
          </Card>
        ) : (
          <>
            {/* 内容区域 */}
            <div style={{
              flex: 1,
              display: 'flex',
              gap: isMobile ? 0 : 16,
              overflow: 'hidden'
            }}>
              <Card
                style={{ flex: 1, overflow: 'auto' }}
                bodyStyle={{ padding: isMobile ? '12px' : '24px' }}
              >
                <Space direction="vertical" style={{ width: '100%' }} size={isMobile ? 'middle' : 'large'}>
                <Card
                  title="组织详情"
                  size="small"
                  extra={
                    <Space>
                      <Button
                        type="link"
                        size="small"
                        icon={<HighlightOutlined />}
                        loading={isOptimizingOrg}
                        onClick={handleOptimizeOrganization}
                      >
                        AI优化
                      </Button>
                      <Button
                        type="link"
                        size="small"
                        icon={<EditOutlined />}
                        onClick={() => {
                          editOrgForm.setFieldsValue({
                            power_level: selectedOrg.power_level,
                            location: selectedOrg.location,
                            motto: selectedOrg.motto,
                            color: selectedOrg.color
                          });
                          setIsEditOrgModalOpen(true);
                        }}
                      >
                        编辑
                      </Button>
                    </Space>
                  }
                >
                  <Descriptions column={isMobile ? 1 : 2} size="small">
                    <Descriptions.Item label="组织名称">{selectedOrg.name}</Descriptions.Item>
                    <Descriptions.Item label="类型">{selectedOrg.type}</Descriptions.Item>
                    <Descriptions.Item label="成员数量">{selectedOrg.member_count}</Descriptions.Item>
                    <Descriptions.Item label="势力等级">
                      <Tag color={selectedOrg.power_level >= 70 ? 'red' : selectedOrg.power_level >= 50 ? 'orange' : 'default'}>
                        {selectedOrg.power_level}
                      </Tag>
                    </Descriptions.Item>
                    {selectedOrg.location && (
                      <Descriptions.Item label="所在地" span={isMobile ? 1 : 2}>
                        {selectedOrg.location}
                      </Descriptions.Item>
                    )}
                    {selectedOrg.color && (
                      <Descriptions.Item label="代表颜色">
                        {selectedOrg.color}
                      </Descriptions.Item>
                    )}
                    {selectedOrg.motto && (
                      <Descriptions.Item label="格言/口号" span={2}>
                        {selectedOrg.motto}
                      </Descriptions.Item>
                    )}
                    <Descriptions.Item label="组织目的" span={2}>
                      {selectedOrg.purpose}
                    </Descriptions.Item>
                  </Descriptions>
                </Card>

                <Card
                  title={`组织成员 (${members.length})`}
                  extra={
                    <Button
                      type="primary"
                      size="small"
                      icon={<PlusOutlined />}
                      onClick={() => setIsAddMemberModalOpen(true)}
                      disabled={availableCharacters.length === 0}
                    >
                      添加成员
                    </Button>
                  }
                >
                  <Table
                    columns={memberColumns}
                    dataSource={members}
                    rowKey="id"
                    pagination={
                      members.length > 5
                        ? {
                          defaultPageSize: 5,
                          showSizeChanger: true,
                          showQuickJumper: !isMobile,
                          showTotal: (total) => `共 ${total} 名成员`,
                          pageSizeOptions: [5, 10, 20],
                          simple: isMobile,
                          position: ['bottomCenter'],
                        }
                        : false
                    }
                    size="small"
                    scroll={{
                      x: isMobile ? 'max-content' : undefined,
                      y: members.length > 10 ? 500 : undefined,
                    }}
                  />
                </Card>
                </Space>
              </Card>
            </div>
          </>
        )}
        </div>
      </div>

      {/* 添加成员模态框 */}
      <Modal
        title="添加组织成员"
        open={isAddMemberModalOpen}
        onCancel={() => {
          setIsAddMemberModalOpen(false);
          form.resetFields();
        }}
        footer={null}
        centered={!isMobile}
        width={isMobile ? '100%' : 500}
        style={isMobile ? { top: 0, paddingBottom: 0, maxWidth: '100vw' } : undefined}
        styles={isMobile ? { body: { maxHeight: 'calc(100vh - 110px)', overflowY: 'auto' } } : undefined}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleAddMember}
        >
          <Form.Item
            name="character_id"
            label="选择角色"
            rules={[{ required: true, message: '请选择角色' }]}
          >
            <Select
              placeholder="选择要加入的角色"
              showSearch
              filterOption={(input, option) =>
                (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
              }
              options={availableCharacters.map(c => ({
                label: c.name,
                value: c.id
              }))}
            />
          </Form.Item>

          <Form.Item
            name="position"
            label="职位"
            rules={[{ required: true, message: '请输入职位' }]}
          >
            <Input placeholder="如：掌门、长老、弟子" />
          </Form.Item>

          <Form.Item
            name="rank"
            label="职位等级"
            initialValue={5}
            tooltip="数字越大等级越高"
          >
            <InputNumber min={0} max={10} style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item
            name="loyalty"
            label="初始忠诚度"
            initialValue={50}
          >
            <InputNumber min={0} max={100} style={{ width: '100%' }} addonAfter="%" />
          </Form.Item>

          <Form.Item
            name="status"
            label="状态"
            initialValue="active"
          >
            <Select>
              <Select.Option value="active">在职</Select.Option>
              <Select.Option value="retired">退休</Select.Option>
              <Select.Option value="expelled">除名</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="joined_at"
            label="加入时间"
          >
            <Input placeholder="如：开山大典时、三年前、建立之初等" />
          </Form.Item>

          <Form.Item>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button onClick={() => setIsAddMemberModalOpen(false)}>取消</Button>
              <Button type="primary" htmlType="submit">
                添加
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑成员模态框 */}
      <Modal
        title="编辑成员信息"
        open={isEditMemberModalOpen}
        onCancel={() => {
          setIsEditMemberModalOpen(false);
          editMemberForm.resetFields();
          setEditingMember(null);
        }}
        footer={null}
        centered={true}
        width={isMobile ? '90%' : 500}
        style={isMobile ? {
          maxWidth: '90vw',
          margin: '0 auto'
        } : undefined}
        styles={isMobile ? {
          body: {
            maxHeight: 'calc(80vh - 110px)',
            overflowY: 'auto',
            padding: '20px 16px'
          }
        } : undefined}
      >
        <Form
          form={editMemberForm}
          layout="vertical"
          onFinish={handleUpdateMember}
        >
          <Form.Item
            name="position"
            label="职位"
            rules={[{ required: true, message: '请输入职位' }]}
          >
            <Input placeholder="如：掌门、长老、弟子" />
          </Form.Item>

          <Form.Item
            name="rank"
            label="职位等级"
            tooltip="数字越大等级越高"
          >
            <InputNumber min={0} max={10} style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item
            name="loyalty"
            label="忠诚度"
          >
            <InputNumber min={0} max={100} style={{ width: '100%' }} addonAfter="%" />
          </Form.Item>

          <Form.Item
            name="contribution"
            label="贡献度"
          >
            <InputNumber min={0} max={100} style={{ width: '100%' }} addonAfter="%" />
          </Form.Item>

          <Form.Item
            name="status"
            label="状态"
          >
            <Select>
              <Select.Option value="active">在职</Select.Option>
              <Select.Option value="retired">退休</Select.Option>
              <Select.Option value="expelled">除名</Select.Option>
              <Select.Option value="deceased">已故</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="joined_at"
            label="加入时间"
          >
            <Input placeholder="如：开山大典时、三年前、建立之初等" />
          </Form.Item>

          <Form.Item
            name="notes"
            label="备注"
          >
            <Input.TextArea rows={3} placeholder="成员相关的备注信息" />
          </Form.Item>

          <Form.Item>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button onClick={() => {
                setIsEditMemberModalOpen(false);
                editMemberForm.resetFields();
                setEditingMember(null);
              }}>
                取消
              </Button>
              <Button type="primary" htmlType="submit">
                保存
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑组织模态框 */}
      <Modal
        title="编辑组织信息"
        open={isEditOrgModalOpen}
        onCancel={() => {
          setIsEditOrgModalOpen(false);
          editOrgForm.resetFields();
        }}
        footer={null}
        centered={!isMobile}
        width={isMobile ? '100%' : 500}
        style={isMobile ? { top: 0, paddingBottom: 0, maxWidth: '100vw' } : undefined}
        styles={isMobile ? { body: { maxHeight: 'calc(100vh - 110px)', overflowY: 'auto' } } : undefined}
      >
        <Form
          form={editOrgForm}
          layout="vertical"
          onFinish={async (values) => {
            if (!selectedOrg) return;
            try {
              await axios.put(`/api/organizations/${selectedOrg.id}`, values);
              message.success('组织信息更新成功');
              setIsEditOrgModalOpen(false);
              editOrgForm.resetFields();

              // 重新获取更新后的组织列表
              const res = await axios.get(`/api/organizations/project/${projectId}`);
              setOrganizations(res.data);

              // 更新当前选中的组织详情
              const updatedOrg = res.data.find((org: Organization) => org.id === selectedOrg.id);
              if (updatedOrg) {
                setSelectedOrg(updatedOrg);
              }

              // 刷新全局 store
              await refreshCharacters();
            } catch (error) {
              message.error('更新失败');
              console.error(error);
            }
          }}
        >
          <Form.Item
            name="power_level"
            label="势力等级"
            rules={[{ required: true, message: '请输入势力等级' }]}
            tooltip="0-100的数值，表示组织的影响力"
          >
            <InputNumber min={0} max={100} style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item
            name="location"
            label="所在地"
          >
            <Input placeholder="组织的主要活动区域或总部位置" />
          </Form.Item>

          <Form.Item
            name="motto"
            label="格言/口号"
          >
            <Input placeholder="组织的宗旨、格言或口号" />
          </Form.Item>

          <Form.Item
            name="color"
            label="代表颜色"
          >
            <Input placeholder="如：深红色、金色、黑色等" />
          </Form.Item>

          <Form.Item>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button onClick={() => setIsEditOrgModalOpen(false)}>取消</Button>
              <Button type="primary" htmlType="submit">
                保存
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 手动创建组织模态框 */}
      <Modal
        title="手动添加组织"
        open={isCreateOrgModalOpen}
        onCancel={() => {
          setIsCreateOrgModalOpen(false);
          createOrgForm.resetFields();
        }}
        footer={null}
        centered={!isMobile}
        width={isMobile ? '100%' : 620}
        style={isMobile ? { top: 0, paddingBottom: 0, maxWidth: '100vw' } : undefined}
        styles={isMobile ? { body: { maxHeight: 'calc(100vh - 110px)', overflowY: 'auto' } } : undefined}
      >
        <Form
          form={createOrgForm}
          layout="vertical"
          onFinish={handleCreateOrganization}
          initialValues={{ power_level: 50 }}
        >
          <Form.Item
            name="name"
            label="组织名称"
            rules={[{ required: true, message: '请输入组织名称' }]}
          >
            <Input placeholder="如：舰载机联络处、帝国总参谋部" />
          </Form.Item>
          <Form.Item name="organization_type" label="组织类型">
            <Input placeholder="如：军方、公司、学院、秘密结社" />
          </Form.Item>
          <Form.Item name="organization_purpose" label="组织目的">
            <TextArea rows={3} placeholder="这个组织的目标、职能或存在意义" />
          </Form.Item>
          <Form.Item name="background" label="组织背景">
            <TextArea rows={3} placeholder="组织历史、来源、矛盾或与主线的关系" />
          </Form.Item>
          <Form.Item name="power_level" label="势力等级">
            <InputNumber min={0} max={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="location" label="所在地">
            <Input placeholder="组织常驻地点或活动范围" />
          </Form.Item>
          <Form.Item name="motto" label="格言/口号">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item name="color" label="代表颜色">
            <Input placeholder="如：深蓝、银白、黑金" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button onClick={() => setIsCreateOrgModalOpen(false)}>取消</Button>
              <Button type="primary" htmlType="submit">保存组织</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <SSELoadingOverlay
        loading={isGeneratingOrg}
        progress={progress}
        message={progressMessage}
      />
    </div>
  );
}
