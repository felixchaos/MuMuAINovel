import { useEffect, useState } from 'react';
import { Alert, Button, Card, Col, Form, Input, InputNumber, Row, Select, Space, Spin, Switch, Tabs, Typography, message, theme } from 'antd';
import { CheckCircleOutlined, MailOutlined, ReloadOutlined, SaveOutlined, SendOutlined, SettingOutlined } from '@ant-design/icons';
import { authApi, settingsApi } from '../services/api';
import type { SystemSMTPSettings, SystemSMTPSettingsUpdate, User } from '../types';

const { Title, Text, Paragraph } = Typography;
const { Option } = Select;

const qqDefaults: Pick<SystemSMTPSettings, 'smtp_provider' | 'smtp_host' | 'smtp_port' | 'smtp_use_ssl' | 'smtp_use_tls'> = {
  smtp_provider: 'qq',
  smtp_host: 'smtp.qq.com',
  smtp_port: 465,
  smtp_use_ssl: true,
  smtp_use_tls: false,
};

export default function SystemSettingsPage() {
  const { token } = theme.useToken();
  const [form] = Form.useForm<SystemSMTPSettingsUpdate>();
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testTargetEmail, setTestTargetEmail] = useState('');

  const pageBackground = `linear-gradient(180deg, ${token.colorBgLayout} 0%, ${token.colorFillSecondary} 100%)`;
  const headerBackground = `linear-gradient(135deg, ${token.colorPrimary} 0%, ${token.colorPrimaryHover} 100%)`;
  const footerSafeOffset = 88;

  const loadData = async () => {
    setInitialLoading(true);
    try {
      const [user, smtpSettings] = await Promise.all([
        authApi.getCurrentUser(),
        settingsApi.getSystemSMTPSettings(),
      ]);
      setCurrentUser(user);
      form.setFieldsValue(smtpSettings);
    } catch (error) {
      console.error('加载系统设置失败:', error);
      message.error('加载系统设置失败');
    } finally {
      setInitialLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleProviderChange = (value: string) => {
    if (value === 'qq') {
      form.setFieldsValue(qqDefaults);
    }
  };

  const handleSave = async (values: SystemSMTPSettingsUpdate) => {
    setSaving(true);
    try {
      const payload = values.smtp_provider === 'qq'
        ? {
            ...values,
            ...qqDefaults,
            smtp_username: values.smtp_username,
            smtp_password: values.smtp_password,
            smtp_from_email: values.smtp_from_email,
            smtp_from_name: values.smtp_from_name,
            email_auth_enabled: values.email_auth_enabled,
            email_register_enabled: values.email_register_enabled,
            verification_code_ttl_minutes: values.verification_code_ttl_minutes,
            verification_resend_interval_seconds: values.verification_resend_interval_seconds,
          }
        : values;
      const result = await settingsApi.updateSystemSMTPSettings(payload);
      form.setFieldsValue(result);
      message.success('系统 SMTP 设置已保存');
    } catch (error) {
      console.error('保存系统设置失败:', error);
      message.error('保存系统设置失败');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    const toEmail = testTargetEmail.trim();
    if (!toEmail) {
      message.warning('请先填写测试目标邮箱');
      return;
    }

    setTesting(true);
    try {
      const result = await settingsApi.testSystemSMTPSettings({ to_email: toEmail });
      if (result.success) {
        message.success(result.message);
      } else {
        message.error(result.message || 'SMTP 测试失败');
      }
    } catch (error) {
      console.error('测试 SMTP 配置失败:', error);
      message.error('测试 SMTP 配置失败');
    } finally {
      setTesting(false);
    }
  };

  if (initialLoading) {
    return (
      <div style={{ minHeight: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: token.colorBgLayout }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!currentUser?.is_admin) {
    return (
      <div style={{ padding: 24 }}>
        <Alert type="error" showIcon message="无权限访问" description="只有管理员可以访问系统设置。" />
      </div>
    );
  }

  return (
    <div
      style={{
        minHeight: `calc(100vh - ${footerSafeOffset}px)`,
        boxSizing: 'border-box',
        background: pageBackground,
        padding: 24,
        paddingBottom: footerSafeOffset,
      }}
    >
      <Card
        bordered={false}
        style={{
          marginBottom: 24,
          borderRadius: 20,
          overflow: 'hidden',
          boxShadow: `0 12px 32px ${token.colorFillSecondary}`,
        }}
        bodyStyle={{ padding: 0 }}
      >
        <div style={{ background: headerBackground, padding: '28px 32px', color: '#fff' }}>
          <Space direction="vertical" size={6}>
            <Space>
              <SettingOutlined />
              <Title level={3} style={{ color: '#fff', margin: 0 }}>系统设置</Title>
            </Space>
            <Paragraph style={{ color: 'rgba(255,255,255,0.88)', margin: 0 }}>
              仅管理员可见，用于维护 SMTP 发信能力、新用户注册与验证码相关系统参数。
            </Paragraph>
          </Space>
        </div>
      </Card>

      <Tabs
        defaultActiveKey="smtp"
        items={[
          {
            key: 'smtp',
            label: (
              <Space>
                <MailOutlined />
                SMTP 配置
              </Space>
            ),
            children: (
              <Form form={form} layout="vertical" onFinish={handleSave}>
                <Row gutter={24}>
                  <Col xs={24} xl={16}>
                    <Card title="邮件服务配置" bordered={false} style={{ borderRadius: 16 }}>
                      <Alert
                        type="info"
                        showIcon
                        style={{ marginBottom: 20 }}
                        message="QQ 邮箱配置说明"
                        description="如果选择 QQ 邮箱，请使用完整 QQ 邮箱地址作为用户名，密码处填写 SMTP 授权码，而不是 QQ 登录密码。默认推荐 smtp.qq.com + SSL 465。"
                      />

                      <Row gutter={16}>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_provider" label="邮件服务商" rules={[{ required: true, message: '请选择邮件服务商' }]}>
                            <Select onChange={handleProviderChange}>
                              <Option value="qq">QQ 邮箱</Option>
                              <Option value="custom">自定义 SMTP</Option>
                            </Select>
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_host" label="SMTP 主机" rules={[{ required: true, message: '请输入 SMTP 主机' }]}>
                            <Input placeholder="例如：smtp.qq.com" />
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_port" label="SMTP 端口" rules={[{ required: true, message: '请输入 SMTP 端口' }]}>
                            <InputNumber style={{ width: '100%' }} min={1} max={65535} />
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_username" label="SMTP 用户名" rules={[{ required: true, message: '请输入 SMTP 用户名' }]}>
                            <Input placeholder="完整邮箱地址" />
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_password" label="SMTP 密码 / 授权码" rules={[{ required: true, message: '请输入 SMTP 授权码' }]}>
                            <Input.Password placeholder="QQ 邮箱请填写授权码" />
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_from_email" label="发件人邮箱">
                            <Input placeholder="默认可与用户名一致" />
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_from_name" label="发件人名称" rules={[{ required: true, message: '请输入发件人名称' }]}>
                            <Input placeholder="MuMuAINovel" />
                          </Form.Item>
                        </Col>
                      </Row>

                      <Row gutter={16}>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_use_ssl" label="启用 SSL" valuePropName="checked">
                            <Switch />
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_use_tls" label="启用 TLS" valuePropName="checked">
                            <Switch />
                          </Form.Item>
                        </Col>
                      </Row>
                    </Card>
                  </Col>

                  <Col xs={24} xl={8}>
                    <Card title="注册与验证码策略" bordered={false} style={{ borderRadius: 16, marginBottom: 24 }}>
                      <Form.Item name="email_auth_enabled" label="启用邮箱认证" valuePropName="checked">
                        <Switch />
                      </Form.Item>
                      <Form.Item
                        name="email_register_enabled"
                        label="允许新用户注册"
                        valuePropName="checked"
                        extra="关闭后，邮箱注册和首次 LinuxDO 登录创建账号都会被拒绝；已有用户仍可登录。"
                      >
                        <Switch checkedChildren="开放" unCheckedChildren="关闭" />
                      </Form.Item>
                      <Form.Item name="verification_code_ttl_minutes" label="验证码有效期（分钟）" rules={[{ required: true, message: '请输入验证码有效期' }]}>
                        <InputNumber style={{ width: '100%' }} min={1} max={120} />
                      </Form.Item>
                      <Form.Item name="verification_resend_interval_seconds" label="验证码重发间隔（秒）" rules={[{ required: true, message: '请输入验证码重发间隔' }]}>
                        <InputNumber style={{ width: '100%' }} min={10} max={3600} />
                      </Form.Item>
                    </Card>

                    <Card title="操作" bordered={false} style={{ borderRadius: 16 }}>
                      <Space direction="vertical" style={{ width: '100%' }} size={12}>
                        <Input
                          value={testTargetEmail}
                          onChange={(e) => setTestTargetEmail(e.target.value)}
                          placeholder="请输入测试目标邮箱，如 123456@qq.com"
                        />
                        <Button icon={<ReloadOutlined />} onClick={loadData} block>
                          重新加载
                        </Button>
                        <Button icon={<SendOutlined />} loading={testing} onClick={handleTest} block>
                          发送测试邮件
                        </Button>
                        <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving} block onClick={() => form.submit()}>
                          保存系统设置
                        </Button>
                        <Alert
                          type="success"
                          showIcon
                          icon={<CheckCircleOutlined />}
                          message="建议使用 QQ 默认配置"
                          description={<Text type="secondary">先保存 SMTP 配置，再填写测试目标邮箱，点击“发送测试邮件”后由后端通过 SMTP 实际发信。</Text>}
                        />
                      </Space>
                    </Card>
                  </Col>
                </Row>
              </Form>
            ),
          },
        ]}
      />
    </div>
  );
}
