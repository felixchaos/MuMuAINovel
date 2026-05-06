import { useEffect, useMemo, useState } from 'react';
import { Alert, AutoComplete, Checkbox, Form, Select, Space, Tag, Typography } from 'antd';
import type { FormInstance } from 'antd/es/form';
import { settingsApi } from '../services/api';
import type { APIKeyPreset, Settings } from '../types';

const DEFAULT_PROFILE_VALUE = '__default__';
const STORAGE_KEY = 'mumu_ai_dialog_polish_config_v1';

export interface AIDialogConfigValues {
  ai_preset_id?: string;
  ai_provider?: string;
  ai_model?: string;
  ai_save_settings?: boolean;
}

export interface ResolvedAIDialogConfig {
  preset_id?: string;
  provider?: string;
  model?: string;
}

interface SavedDialogConfig {
  presetId?: string;
  provider?: string;
  model?: string;
}

interface AIDialogConfigPanelProps {
  form: FormInstance;
  disabled?: boolean;
  compact?: boolean;
}

function readSavedDialogConfig(): SavedDialogConfig | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as SavedDialogConfig;
    return typeof data === 'object' && data !== null ? data : null;
  } catch {
    return null;
  }
}

function writeSavedDialogConfig(config: SavedDialogConfig) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch {
    // 本地缓存失败不影响本次AI请求
  }
}

function normalizePresetId(value?: string) {
  return value && value !== DEFAULT_PROFILE_VALUE ? value : undefined;
}

function buildModelOptions(settings?: Settings | null, presets: APIKeyPreset[] = []) {
  const seen = new Set<string>();
  const models = [
    settings?.llm_model,
    ...presets.map((preset) => preset.config?.llm_model),
  ].filter((model): model is string => Boolean(model && model.trim()));

  return models
    .filter((model) => {
      if (seen.has(model)) return false;
      seen.add(model);
      return true;
    })
    .map((model) => ({ value: model, label: model }));
}

export function normalizeAIDialogConfig(values: Partial<AIDialogConfigValues>): ResolvedAIDialogConfig {
  const presetId = normalizePresetId(values.ai_preset_id);
  const provider = values.ai_provider?.trim() || undefined;
  const model = values.ai_model?.trim() || undefined;
  return {
    preset_id: presetId,
    provider,
    model,
  };
}

export async function resolveAIDialogConfig(values: Partial<AIDialogConfigValues>): Promise<ResolvedAIDialogConfig> {
  const config = normalizeAIDialogConfig(values);

  if (values.ai_save_settings) {
    try {
      await settingsApi.setPolishPresetSelection(config.preset_id);
      if (!config.preset_id && config.model) {
        await settingsApi.updateSettings({ llm_model: config.model });
      }
      writeSavedDialogConfig({
        presetId: config.preset_id,
        provider: config.provider,
        model: config.model,
      });
    } catch (error) {
      console.warn('保存AI弹窗设置失败:', error);
    }
  }

  return config;
}

export function AIDialogConfigPanel({ form, disabled, compact = false }: AIDialogConfigPanelProps) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [presets, setPresets] = useState<APIKeyPreset[]>([]);
  const [polishPresetId, setPolishPresetId] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const loadConfig = async () => {
      setLoading(true);
      try {
        const [settingsResponse, presetsResponse] = await Promise.all([
          settingsApi.getSettings(),
          settingsApi.getPresets(),
        ]);
        if (cancelled) return;

        setSettings(settingsResponse);
        setPresets(presetsResponse.presets || []);
        setPolishPresetId(presetsResponse.polish_preset_id);

        const saved = readSavedDialogConfig();
        const savedPresetExists = saved?.presetId
          ? (presetsResponse.presets || []).some((preset) => preset.id === saved.presetId)
          : false;
        const selectedPresetId = savedPresetExists
          ? saved?.presetId
          : presetsResponse.polish_preset_id;
        const selectedPreset = selectedPresetId
          ? (presetsResponse.presets || []).find((preset) => preset.id === selectedPresetId)
          : undefined;

        form.setFieldsValue({
          ai_preset_id: selectedPresetId || DEFAULT_PROFILE_VALUE,
          ai_provider: selectedPreset?.config.api_provider || saved?.provider || settingsResponse.api_provider,
          ai_model: saved?.model || selectedPreset?.config.llm_model || settingsResponse.llm_model,
          ai_save_settings: false,
        });
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadConfig();
    return () => {
      cancelled = true;
    };
  }, [form]);

  const modelOptions = useMemo(() => buildModelOptions(settings, presets), [settings, presets]);
  const polishPreset = polishPresetId ? presets.find((preset) => preset.id === polishPresetId) : undefined;

  const handlePresetChange = (value?: string) => {
    const presetId = normalizePresetId(value);
    const preset = presetId ? presets.find((item) => item.id === presetId) : undefined;
    form.setFieldsValue({
      ai_provider: preset?.config.api_provider || settings?.api_provider,
      ai_model: preset?.config.llm_model || settings?.llm_model,
    });
  };

  return (
    <div style={{ display: 'grid', gap: compact ? 8 : 12 }}>
      <Alert
        type="info"
        showIcon
        message={
          <Space size={6} wrap>
            <Typography.Text>当前默认模型</Typography.Text>
            <Tag>{settings ? `${settings.api_provider} / ${settings.llm_model}` : '加载中'}</Tag>
            <Typography.Text>润色/优化配置</Typography.Text>
            <Tag color={polishPreset ? 'purple' : undefined}>
              {polishPreset ? `${polishPreset.name} / ${polishPreset.config.llm_model}` : '默认配置'}
            </Tag>
          </Space>
        }
        style={{ marginBottom: compact ? 0 : 4 }}
      />
      <Form.Item name="ai_provider" hidden>
        <input />
      </Form.Item>
      <Form.Item label="配置文件" name="ai_preset_id" style={{ marginBottom: compact ? 8 : undefined }}>
        <Select
          loading={loading}
          disabled={disabled}
          onChange={handlePresetChange}
          options={[
            { label: '默认配置', value: DEFAULT_PROFILE_VALUE },
            ...presets.map((preset) => ({
              label: `${preset.name} (${preset.config.llm_model})`,
              value: preset.id,
            })),
          ]}
        />
      </Form.Item>
      <Form.Item
        label="模型"
        name="ai_model"
        tooltip="可以直接输入模型名；留空时使用所选配置文件里的默认模型。"
        style={{ marginBottom: compact ? 8 : undefined }}
      >
        <AutoComplete
          disabled={disabled}
          allowClear
          options={modelOptions}
          placeholder={settings?.llm_model ? `默认：${settings.llm_model}` : '输入或选择模型'}
          filterOption={(inputValue, option) =>
            String(option?.value || '').toLowerCase().includes(inputValue.toLowerCase())
          }
        />
      </Form.Item>
      <Form.Item name="ai_save_settings" valuePropName="checked" style={{ marginBottom: 0 }}>
        <Checkbox disabled={disabled}>保存当前设置</Checkbox>
      </Form.Item>
    </div>
  );
}

