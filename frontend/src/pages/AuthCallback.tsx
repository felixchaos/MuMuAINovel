import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Spin, Result, Button, Modal, Input, message, theme } from 'antd';
import { authApi } from '../services/api';
import AnnouncementModal from '../components/AnnouncementModal';
import { FEATURE_FLAGS } from '../config/featureFlags';

export default function AuthCallback() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [errorMessage, setErrorMessage] = useState('');
  const [showAnnouncement, setShowAnnouncement] = useState(false);
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const { token } = theme.useToken();
  const alphaColor = (color: string, alpha: number) => `color-mix(in srgb, ${color} ${(alpha * 100).toFixed(0)}%, transparent)`;
  interface PasswordStatus {
    has_password: boolean;
    has_custom_password: boolean;
    username: string;
    default_password: string;
  }
  const [passwordStatus, setPasswordStatus] = useState<PasswordStatus | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [settingPassword, setSettingPassword] = useState(false);

  useEffect(() => {
    const handleCallback = async () => {
      try {
        // 后端会通过 Cookie 自动设置认证信息
        // 这里只需要验证登录状态
        const currentUser = await authApi.getCurrentUser();

        // 检查是否是首次登录（通过 Cookie 标记）
        const isFirstLogin = document.cookie.includes('first_login=true');
        
        setStatus('success');

        if (isFirstLogin) {
          // 首次登录：生成默认密码并显示提示
          const defaultPassword = `${currentUser.username}@666`;
          const pwdStatus = {
            has_password: false,
            has_custom_password: false,
            username: currentUser.username,
            default_password: defaultPassword
          };
          setPasswordStatus(pwdStatus);

          // 清除首次登录标记 Cookie
          document.cookie = 'first_login=; path=/; max-age=0';

          // 显示密码初始化弹窗
          setTimeout(() => {
            setShowPasswordModal(true);
          }, 1000);
          return;
        }

        // 非首次登录：正常流程
        // 从 sessionStorage 获取重定向地址
        const redirect = sessionStorage.getItem('login_redirect') || '/';
        sessionStorage.removeItem('login_redirect');

        // 检查是否永久隐藏公告或今日已隐藏
        const hideForever = localStorage.getItem('announcement_hide_forever');
        const hideToday = localStorage.getItem('announcement_hide_today');
        const today = new Date().toDateString();

        if (!FEATURE_FLAGS.announcementModal || hideForever === 'true' || hideToday === today) {
          // 延迟一下再跳转，让用户看到成功提示
          setTimeout(() => {
            navigate(redirect);
          }, 1000);
        } else {
          // 延迟一下再显示公告，让用户看到成功提示
          setTimeout(() => {
            setShowAnnouncement(true);
          }, 1000);
        }
      } catch (error) {
        console.error('登录失败:', error);
        setStatus('error');
        setErrorMessage('登录失败，请重试');
      }
    };

    handleCallback();
  }, [navigate]);

  if (status === 'loading') {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        background: `linear-gradient(135deg, ${token.colorPrimary} 0%, ${token.colorPrimaryHover} 100%)`,
      }}>
        <div style={{ textAlign: 'center' }}>
          <Spin size="large" />
          <div style={{ marginTop: 20, color: token.colorWhite, fontSize: 16 }}>
            正在处理登录...
          </div>
        </div>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        background: `linear-gradient(135deg, ${token.colorPrimary} 0%, ${token.colorPrimaryHover} 100%)`,
      }}>
        <Result
          status="error"
          title="登录失败"
          subTitle={errorMessage}
          extra={
            <Button type="primary" onClick={() => navigate('/login')}>
              返回登录
            </Button>
          }
          style={{ background: token.colorBgContainer, padding: 40, borderRadius: 8 }}
        />
      </div>
    );
  }

  const handleAnnouncementClose = () => {
    setShowAnnouncement(false);
    const redirect = sessionStorage.getItem('login_redirect') || '/';
    sessionStorage.removeItem('login_redirect');
    navigate(redirect);
  };

  const handleDoNotShowToday = () => {
    // 设置今日不再显示
    const today = new Date().toDateString();
    localStorage.setItem('announcement_hide_today', today);
  };

  const handleNeverShow = () => {
    // 设置永久不再显示
    localStorage.setItem('announcement_hide_forever', 'true');
  };

  const handleSetPassword = async () => {
    // 如果没有输入新密码，使用默认密码
    const passwordToSet = newPassword || passwordStatus?.default_password;
    
    if (!passwordToSet) {
      message.error('请输入新密码');
      return;
    }
    if (passwordToSet.length < 6) {
      message.error('密码长度至少为6个字符');
      return;
    }
    if (newPassword && newPassword !== confirmPassword) {
      message.error('两次输入的密码不一致');
      return;
    }

    setSettingPassword(true);
    try {
      // 首次登录使用初始化接口，后续使用修改接口
      const isFirstLogin = !passwordStatus?.has_password;
      if (isFirstLogin) {
        await authApi.initializePassword(passwordToSet);
        message.success('密码初始化成功');
      } else {
        await authApi.setPassword(passwordToSet);
        message.success('密码设置成功');
      }
      setShowPasswordModal(false);

      // 继续后续流程
      const redirect = sessionStorage.getItem('login_redirect') || '/';
      sessionStorage.removeItem('login_redirect');

      const hideForever = localStorage.getItem('announcement_hide_forever');
      const hideToday = localStorage.getItem('announcement_hide_today');
      const today = new Date().toDateString();

      if (!FEATURE_FLAGS.announcementModal || hideForever === 'true' || hideToday === today) {
        setTimeout(() => {
          navigate(redirect);
        }, 500);
      } else {
        setTimeout(() => {
          setShowAnnouncement(true);
        }, 500);
      }
    } catch {
      message.error('密码设置失败，请重试');
    } finally {
      setSettingPassword(false);
    }
  };

  const handleSkipPasswordSetting = async () => {
    // 首次登录时，如果跳过设置，使用默认密码初始化
    const isFirstLogin = !passwordStatus?.has_password;
    if (isFirstLogin && passwordStatus?.default_password) {
      try {
        await authApi.initializePassword(passwordStatus.default_password);
      } catch (error) {
        console.error('初始化默认密码失败:', error);
      }
    }

    setShowPasswordModal(false);

    // 继续后续流程
    const redirect = sessionStorage.getItem('login_redirect') || '/';
    sessionStorage.removeItem('login_redirect');

    const hideForever = localStorage.getItem('announcement_hide_forever');
    const hideToday = localStorage.getItem('announcement_hide_today');
    const today = new Date().toDateString();

    if (!FEATURE_FLAGS.announcementModal || hideForever === 'true' || hideToday === today) {
      setTimeout(() => {
        navigate(redirect);
      }, 500);
    } else {
      setTimeout(() => {
        setShowAnnouncement(true);
      }, 500);
    }
  };

  return (
    <>
      {FEATURE_FLAGS.announcementModal && (
        <AnnouncementModal
          visible={showAnnouncement}
          onClose={handleAnnouncementClose}
          onDoNotShowToday={handleDoNotShowToday}
          onNeverShow={handleNeverShow}
        />
      )}

      <Modal
        title="设置账号密码"
        open={showPasswordModal}
        centered
        onOk={handleSetPassword}
        onCancel={handleSkipPasswordSetting}
        confirmLoading={settingPassword}
        okText="设置密码"
        cancelText="暂不设置"
        width={500}
      >
        <div style={{ marginBottom: 20 }}>
          <p>您已成功通过 Linux DO 授权登录！</p>
          <p>系统已为您自动生成默认密码，您可以选择设置自定义密码或继续使用默认密码。</p>
          {passwordStatus?.default_password && (
            <div style={{
              background: token.colorFillTertiary,
              padding: 12,
              borderRadius: 4,
              marginTop: 12
            }}>
              <strong>账号：</strong>{passwordStatus.username}<br />
              <strong>默认密码：</strong><code style={{
                background: token.colorBgContainer,
                padding: '2px 8px',
                borderRadius: 3,
                color: token.colorPrimary,
                fontSize: 14
              }}>{passwordStatus.default_password}</code>
            </div>
          )}
        </div>

        <div style={{ marginTop: 20 }}>
          <div style={{ marginBottom: 12 }}>
            <label>新密码（至少6个字符）：</label>
            <Input.Password
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="请输入新密码"
              style={{ marginTop: 4 }}
            />
          </div>
          <div>
            <label>确认密码：</label>
            <Input.Password
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="请再次输入密码"
              style={{ marginTop: 4 }}
            />
          </div>
        </div>
      </Modal>

      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        background: `linear-gradient(135deg, ${token.colorPrimary} 0%, ${token.colorPrimaryHover} 100%)`,
      }}>
        <Result
          status="success"
          title="登录成功"
          subTitle={showPasswordModal ? "请设置账号密码..." : (showAnnouncement ? "欢迎使用..." : "正在跳转...")}
          style={{ background: alphaColor(token.colorBgContainer, 0.96), padding: 40, borderRadius: 8 }}
        />
      </div>
    </>
  );
}
