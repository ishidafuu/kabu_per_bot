import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { AppLayout } from '../components/AppLayout';
import { createTechnicalProfilesClient } from '../lib/api';
import { toUserMessage } from '../lib/api/errors';
import type {
  TechnicalProfile,
  TechnicalProfileCloneInput,
  TechnicalProfileCreateInput,
  TechnicalProfileUpdateInput,
} from '../types/technicalProfiles';

type FormState = {
  profile_key: string;
  name: string;
  description: string;
  base_profile_key: string;
  priority_order: string;
  manual_assign_recommended: boolean;
  auto_assign_json: string;
  thresholds_json: string;
  weights_json: string;
  flags_json: string;
  strong_alerts_text: string;
  weak_alerts_text: string;
  is_active: boolean;
};

const emptyForm = (): FormState => ({
  profile_key: '',
  name: '',
  description: '',
  base_profile_key: '',
  priority_order: '',
  manual_assign_recommended: false,
  auto_assign_json: '{}',
  thresholds_json: '{}',
  weights_json: '{}',
  flags_json: '{}',
  strong_alerts_text: '',
  weak_alerts_text: '',
  is_active: true,
});

const toPrettyJson = (value: unknown): string => JSON.stringify(value ?? {}, null, 2);

const toFormState = (profile: TechnicalProfile): FormState => ({
  profile_key: profile.profile_key,
  name: profile.name,
  description: profile.description,
  base_profile_key: profile.base_profile_key ?? '',
  priority_order: profile.priority_order != null ? String(profile.priority_order) : '',
  manual_assign_recommended: profile.manual_assign_recommended,
  auto_assign_json: toPrettyJson(profile.auto_assign),
  thresholds_json: toPrettyJson(profile.thresholds),
  weights_json: toPrettyJson(profile.weights),
  flags_json: toPrettyJson(profile.flags),
  strong_alerts_text: profile.strong_alerts.join('\n'),
  weak_alerts_text: profile.weak_alerts.join('\n'),
  is_active: profile.is_active,
});

const parseJsonObject = (label: string, raw: string): Record<string, unknown> => {
  try {
    const parsed = JSON.parse(raw);
    if (parsed == null || Array.isArray(parsed) || typeof parsed !== 'object') {
      throw new Error(`${label} はJSONオブジェクトで入力してください。`);
    }
    return parsed as Record<string, unknown>;
  } catch (error) {
    if (error instanceof Error && error.message.includes(label)) {
      throw error;
    }
    throw new Error(`${label} のJSONが不正です。`);
  }
};

const parseNumberMap = (label: string, raw: string): Record<string, number> => {
  const object = parseJsonObject(label, raw);
  const entries = Object.entries(object).map(([key, value]) => [key, Number(value)] as const);
  if (entries.some(([, value]) => Number.isNaN(value))) {
    throw new Error(`${label} は数値マップで入力してください。`);
  }
  return Object.fromEntries(entries);
};

const parseBooleanMap = (label: string, raw: string): Record<string, boolean> => {
  const object = parseJsonObject(label, raw);
  return Object.fromEntries(Object.entries(object).map(([key, value]) => [key, Boolean(value)]));
};

const parseStringList = (raw: string): string[] =>
  raw
    .split('\n')
    .map((row) => row.trim())
    .filter((row) => row.length > 0);

export const TechnicalProfilesPage = () => {
  const { getIdToken } = useAuth();
  const client = useMemo(() => createTechnicalProfilesClient({ getToken: getIdToken }), [getIdToken]);
  const [profiles, setProfiles] = useState<TechnicalProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [form, setForm] = useState<FormState>(emptyForm);
  const [mode, setMode] = useState<'view' | 'create' | 'clone'>('view');
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const selectedProfile = profiles.find((profile) => profile.profile_id === selectedProfileId) ?? null;
  const isSystemProfile = selectedProfile?.profile_type === 'SYSTEM' && mode === 'view';

  const loadProfiles = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setError('');
    try {
      const response = await client.list();
      setProfiles(response.items);
      if (response.items.length > 0) {
        const current = response.items.find((row) => row.profile_id === selectedProfileId) ?? response.items[0];
        setSelectedProfileId(current.profile_id);
        if (mode === 'view') {
          setForm(toFormState(current));
        }
      }
    } catch (loadError) {
      setError(toUserMessage(loadError));
    } finally {
      setIsLoading(false);
    }
  }, [client, mode, selectedProfileId]);

  useEffect(() => {
    void loadProfiles();
  }, [loadProfiles]);

  const selectProfile = (profile: TechnicalProfile): void => {
    setSelectedProfileId(profile.profile_id);
    setForm(toFormState(profile));
    setMode('view');
    setError('');
    setNotice('');
  };

  const beginCreate = (): void => {
    setSelectedProfileId('');
    setForm(emptyForm());
    setMode('create');
    setError('');
    setNotice('');
  };

  const beginClone = (): void => {
    if (!selectedProfile) {
      return;
    }
    setForm({
      ...toFormState(selectedProfile),
      profile_key: `${selectedProfile.profile_key}_copy`,
      name: `${selectedProfile.name} 複製`,
    });
    setMode('clone');
    setError('');
    setNotice('');
  };

  const handleSave = async (): Promise<void> => {
    setIsSaving(true);
    setError('');
    setNotice('');
    try {
      const payloadBase: TechnicalProfileCreateInput = {
        profile_key: form.profile_key.trim(),
        name: form.name.trim(),
        description: form.description.trim(),
        base_profile_key: form.base_profile_key.trim() || null,
        priority_order: form.priority_order.trim() ? Number(form.priority_order) : null,
        manual_assign_recommended: form.manual_assign_recommended,
        auto_assign: parseJsonObject('auto_assign', form.auto_assign_json),
        thresholds: parseNumberMap('thresholds', form.thresholds_json),
        weights: parseNumberMap('weights', form.weights_json),
        flags: parseBooleanMap('flags', form.flags_json),
        strong_alerts: parseStringList(form.strong_alerts_text),
        weak_alerts: parseStringList(form.weak_alerts_text),
        is_active: form.is_active,
      };
      if (!payloadBase.profile_key || !payloadBase.name || !payloadBase.description) {
        throw new Error('profile_key / 名前 / 説明は必須です。');
      }

      let saved: TechnicalProfile;
      if (mode === 'create') {
        saved = await client.create(payloadBase);
        setNotice(`カスタムプロファイルを作成しました: ${saved.name}`);
      } else if (mode === 'clone' && selectedProfile) {
        const clonePayload: TechnicalProfileCloneInput = {
          profile_key: payloadBase.profile_key,
          name: payloadBase.name,
          description: payloadBase.description,
        };
        saved = await client.clone(selectedProfile.profile_id, clonePayload);
        saved = await client.update(saved.profile_id, {
          description: payloadBase.description,
          priority_order: payloadBase.priority_order,
          manual_assign_recommended: payloadBase.manual_assign_recommended,
          auto_assign: payloadBase.auto_assign,
          thresholds: payloadBase.thresholds,
          weights: payloadBase.weights,
          flags: payloadBase.flags,
          strong_alerts: payloadBase.strong_alerts,
          weak_alerts: payloadBase.weak_alerts,
          is_active: payloadBase.is_active,
        });
        setNotice(`プロファイルを複製しました: ${saved.name}`);
      } else if (selectedProfile) {
        const updatePayload: TechnicalProfileUpdateInput = {
          name: payloadBase.name,
          description: payloadBase.description,
          priority_order: payloadBase.priority_order,
          manual_assign_recommended: payloadBase.manual_assign_recommended,
          auto_assign: payloadBase.auto_assign,
          thresholds: payloadBase.thresholds,
          weights: payloadBase.weights,
          flags: payloadBase.flags,
          strong_alerts: payloadBase.strong_alerts,
          weak_alerts: payloadBase.weak_alerts,
          is_active: payloadBase.is_active,
        };
        saved = await client.update(selectedProfile.profile_id, updatePayload);
        setNotice(`カスタムプロファイルを更新しました: ${saved.name}`);
      } else {
        throw new Error('保存対象のプロファイルがありません。');
      }
      await loadProfiles();
      setSelectedProfileId(saved.profile_id);
      setForm(toFormState(saved));
      setMode('view');
    } catch (saveError) {
      setError(toUserMessage(saveError));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <AppLayout title="技術プロファイル" subtitle="デフォルト4種の確認とカスタム運用">
      <section className="content-grid technical-profiles-layout">
        <div className="panel">
          <div className="section-header">
            <div>
              <h2>プロファイル一覧</h2>
              <p className="muted">SYSTEM は閲覧専用です。</p>
            </div>
            <button type="button" onClick={beginCreate}>
              新規カスタムを作成
            </button>
          </div>
          {isLoading ? <p>読み込み中...</p> : null}
          {!isLoading ? (
            <div className="technical-profile-list">
              {profiles.map((profile) => (
                <button
                  key={profile.profile_id}
                  type="button"
                  className={`technical-profile-card${selectedProfileId === profile.profile_id ? ' selected' : ''}`}
                  onClick={() => selectProfile(profile)}
                >
                  <strong>{profile.name}</strong>
                  <span>{profile.profile_type}</span>
                  <small>{profile.description}</small>
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="panel">
          <div className="section-header">
            <div>
              <h2>{mode === 'create' ? 'カスタム作成' : mode === 'clone' ? 'プロファイル複製' : 'プロファイル詳細'}</h2>
              <p className="muted">
                {isSystemProfile ? 'SYSTEM は複製して使ってください。' : 'thresholds / weights / flags は JSON で編集します。'}
              </p>
            </div>
            {selectedProfile && mode === 'view' ? (
              <button type="button" className="ghost" onClick={beginClone}>
                デフォルトから複製
              </button>
            ) : null}
          </div>

          {notice ? <p className="success-text">{notice}</p> : null}
          {error ? <p className="error-text">{error}</p> : null}

          {selectedProfile == null && mode === 'view' ? <p>プロファイルを選択してください。</p> : null}

          {selectedProfile != null || mode !== 'view' ? (
            <div className="stack-form">
              <label>
                profile_key
                <input
                  aria-label="profile_key"
                  value={form.profile_key}
                  onChange={(event) => setForm((current) => ({ ...current, profile_key: event.target.value }))}
                  disabled={mode === 'view'}
                />
              </label>
              <label>
                名前
                <input
                  aria-label="名前"
                  value={form.name}
                  onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                  disabled={isSystemProfile}
                />
              </label>
              <label>
                説明
                <textarea
                  aria-label="説明"
                  rows={3}
                  value={form.description}
                  onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
                  disabled={isSystemProfile}
                />
              </label>
              <label>
                base_profile_key
                <input
                  aria-label="base_profile_key"
                  value={form.base_profile_key}
                  onChange={(event) => setForm((current) => ({ ...current, base_profile_key: event.target.value }))}
                  disabled={isSystemProfile}
                />
              </label>
              <label>
                priority_order
                <input
                  aria-label="priority_order"
                  type="number"
                  value={form.priority_order}
                  onChange={(event) => setForm((current) => ({ ...current, priority_order: event.target.value }))}
                  disabled={isSystemProfile}
                />
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={form.manual_assign_recommended}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, manual_assign_recommended: event.target.checked }))
                  }
                  disabled={isSystemProfile}
                />
                手動割当推奨
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))}
                  disabled={isSystemProfile}
                />
                有効
              </label>
              <label>
                auto_assign(JSON)
                <textarea
                  aria-label="auto_assign(JSON)"
                  rows={6}
                  value={form.auto_assign_json}
                  onChange={(event) => setForm((current) => ({ ...current, auto_assign_json: event.target.value }))}
                  disabled={isSystemProfile}
                />
              </label>
              <label>
                thresholds(JSON)
                <textarea
                  aria-label="thresholds(JSON)"
                  rows={8}
                  value={form.thresholds_json}
                  onChange={(event) => setForm((current) => ({ ...current, thresholds_json: event.target.value }))}
                  disabled={isSystemProfile}
                />
              </label>
              <label>
                weights(JSON)
                <textarea
                  aria-label="weights(JSON)"
                  rows={6}
                  value={form.weights_json}
                  onChange={(event) => setForm((current) => ({ ...current, weights_json: event.target.value }))}
                  disabled={isSystemProfile}
                />
              </label>
              <label>
                flags(JSON)
                <textarea
                  aria-label="flags(JSON)"
                  rows={6}
                  value={form.flags_json}
                  onChange={(event) => setForm((current) => ({ ...current, flags_json: event.target.value }))}
                  disabled={isSystemProfile}
                />
              </label>
              <label>
                strong_alerts
                <textarea
                  aria-label="strong_alerts"
                  rows={4}
                  value={form.strong_alerts_text}
                  onChange={(event) => setForm((current) => ({ ...current, strong_alerts_text: event.target.value }))}
                  disabled={isSystemProfile}
                />
              </label>
              <label>
                weak_alerts
                <textarea
                  aria-label="weak_alerts"
                  rows={4}
                  value={form.weak_alerts_text}
                  onChange={(event) => setForm((current) => ({ ...current, weak_alerts_text: event.target.value }))}
                  disabled={isSystemProfile}
                />
              </label>
              {!isSystemProfile ? (
                <div className="inline-actions">
                  <button type="button" onClick={() => void handleSave()} disabled={isSaving}>
                    {mode === 'create' ? '作成する' : mode === 'clone' ? '複製して保存' : '更新する'}
                  </button>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => {
                      if (selectedProfile) {
                        selectProfile(selectedProfile);
                      } else {
                        beginCreate();
                      }
                    }}
                    disabled={isSaving}
                  >
                    リセット
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </section>
    </AppLayout>
  );
};
