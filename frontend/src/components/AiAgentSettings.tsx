import { useEffect, useMemo, useState } from 'react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { Divider } from '@astryxdesign/core/Divider'
import { FormLayout } from '@astryxdesign/core/FormLayout'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl'
import { Selector } from '@astryxdesign/core/Selector'
import { Slider } from '@astryxdesign/core/Slider'
import { StatusDot } from '@astryxdesign/core/StatusDot'
import { Switch } from '@astryxdesign/core/Switch'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  type AiAgentSettings as Settings,
  type AiAgentSettingsInput,
  type AiConnectionTest,
  type ReasoningEffort,
  type VoiceCallProvider,
  useAiAgentSettings,
  useAiModels,
  useTestAiConnection,
  useUpdateAiAgentSettings,
} from '../api/aiSettings'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { labelMap } from '../utils/labelMap'
import { ChimegeSettings } from './ChimegeSettings'
import { ElevenLabsSettings } from './ElevenLabsSettings'

const CUSTOM = '__custom__'
const NO_FALLBACK = '__none__'

const SOURCE_COLORS: Record<Settings['key_source'], 'green' | 'blue' | 'red'> = { organization: 'green', environment: 'blue', none: 'red' }
const TEST_ERRORS = labelMap('st.ai.testError', ['invalid_key', 'forbidden', 'model_not_found', 'rate_limited', 'not_configured', 'network', 'provider_error', 'rejected'])

function modelOptions(models: string[], ...current: (string | null | undefined)[]) {
  const values = Array.from(new Set([...current.filter((item): item is string => Boolean(item)), ...models]))
  return [...values.map((value) => ({ value, label: value })), { type: 'divider' as const }, { value: CUSTOM, label: i18n.t('st.ai.customModel') }]
}

function ModelField({ label, description, value, models, onChange, allowNone }: {
  label: string
  description: string
  value: string | null
  models: string[]
  onChange: (value: string | null) => void
  allowNone?: boolean
}) {
  const { t } = useTranslation()
  const [custom, setCustom] = useState(false)
  const options = useMemo(() => {
    const base = modelOptions(models, value)
    return allowNone ? [{ value: NO_FALLBACK, label: t('st.ai.noFallback') }, ...base] : base
  }, [models, value, allowNone])
  return <VStack gap={2}>
    <Selector
      label={label}
      description={description}
      options={options}
      value={custom ? CUSTOM : value ?? (allowNone ? NO_FALLBACK : undefined)}
      hasSearch
      searchPlaceholder={t('st.ai.searchModel')}
      onChange={(next) => {
        if (next === CUSTOM) { setCustom(true); return }
        setCustom(false)
        onChange(next === NO_FALLBACK ? null : next)
      }}
    />
    {custom && <TextInput label={t('st.ai.modelIdLabel', { label })} description={t('st.ai.modelIdHint')} value={value ?? ''} onChange={(next) => onChange(next.trim() || null)} />}
  </VStack>
}

export function AiAgentSettings() {
  const { t } = useTranslation()
  const settings = useAiAgentSettings()
  const models = useAiModels(Boolean(settings.data && settings.data.key_source !== 'none'))
  const update = useUpdateAiAgentSettings()
  const testConnection = useTestAiConnection()
  const [apiKey, setApiKey] = useState('')
  const [draft, setDraft] = useState<Required<Pick<AiAgentSettingsInput, 'primary_model' | 'reasoning_effort' | 'max_output_tokens' | 'web_search_enabled'>> & { fallback_model: string | null; realtime_model?: string; realtime_voice?: string; realtime_enabled?: boolean; voice_call_provider?: VoiceCallProvider } | null>(null)
  const [testResult, setTestResult] = useState<AiConnectionTest | null>(null)

  useEffect(() => {
    if (!settings.data) return
    setDraft({
      primary_model: settings.data.primary_model,
      fallback_model: settings.data.fallback_model,
      reasoning_effort: settings.data.reasoning_effort,
      max_output_tokens: settings.data.max_output_tokens,
      web_search_enabled: settings.data.web_search_enabled,
      realtime_model: settings.data.realtime_model,
      realtime_voice: settings.data.realtime_voice,
      realtime_enabled: settings.data.realtime_enabled,
      voice_call_provider: settings.data.voice_call_provider,
    })
  }, [settings.data])

  if (settings.isLoading || !draft) return <Text type="supporting">{t('st.ai.loading')}</Text>
  if (settings.isError || !settings.data) return <Banner status="error" title={t('st.ai.loadFailed')} />

  const data = settings.data
  const source = { label: t(`st.ai.source.${data.key_source}`), color: SOURCE_COLORS[data.key_source] }
  const listed = models.data?.models ?? []
  const dirty = Boolean(apiKey.trim())
    || draft.primary_model !== data.primary_model
    || draft.fallback_model !== data.fallback_model
    || draft.reasoning_effort !== data.reasoning_effort
    || draft.max_output_tokens !== data.max_output_tokens
    || draft.web_search_enabled !== data.web_search_enabled
    || draft.realtime_model !== data.realtime_model
    || draft.realtime_voice !== data.realtime_voice
    || draft.realtime_enabled !== data.realtime_enabled
    || draft.voice_call_provider !== data.voice_call_provider
  const realtimeListed = models.data?.realtime_models ?? []

  const save = async () => {
    try {
      await update.mutateAsync({
        api_key: apiKey.trim() || null,
        primary_model: draft.primary_model,
        fallback_model: draft.fallback_model ?? '',
        reasoning_effort: draft.reasoning_effort,
        max_output_tokens: draft.max_output_tokens,
        web_search_enabled: draft.web_search_enabled,
        ...(draft.realtime_model !== undefined ? { realtime_model: draft.realtime_model } : {}),
        ...(draft.realtime_voice !== undefined ? { realtime_voice: draft.realtime_voice } : {}),
        ...(draft.realtime_enabled !== undefined ? { realtime_enabled: draft.realtime_enabled } : {}),
        ...(draft.voice_call_provider !== undefined ? { voice_call_provider: draft.voice_call_provider } : {}),
      })
      setApiKey('')
    } catch { /* the mutation's onError shows the toast */ }
  }

  const runTest = async () => {
    try {
      setTestResult(await testConnection.mutateAsync({ api_key: apiKey.trim() || null, model: draft.primary_model }))
    } catch {
      setTestResult({ ok: false, error: 'network', latency_ms: null, model: draft.primary_model })
    }
  }

  return <VStack gap={4}>
    <Card padding={5}>
      <VStack gap={4}>
        <HStack gap={2} vAlign="center" wrap="wrap">
          <Heading level={3}>{t('st.ai.keyTitle')}</Heading>
          <Token size="sm" color={source.color} label={source.label} />
          {data.has_key && data.key_last4 && <Token size="sm" label={`sk-…${data.key_last4}`} />}
        </HStack>
        <Text type="supporting">{t('st.ai.keyHint')}</Text>
        <TextInput
          type="password"
          label={data.has_key ? t('st.ai.replaceKey') : t('st.ai.apiKey')}
          description={t('st.ai.keyFormat')}
          value={apiKey}
          onChange={setApiKey}
          isOptional={data.key_source !== 'none'}
        />
        {data.has_key && <HStack gap={2}>
          <Button label={t('st.ai.deleteKey')} variant="destructive" size="sm" isLoading={update.isPending} onClick={() => { if (window.confirm(t('st.ai.deleteKeyConfirm'))) update.mutate({ clear_api_key: true }) }} />
        </HStack>}
      </VStack>
    </Card>

    <Card padding={5}>
      <VStack gap={4}>
        <Heading level={3}>{t('st.ai.modelSection')}</Heading>
        {models.data?.error && <Banner status="warning" title={t('st.ai.modelsFailed')} description={TEST_ERRORS[models.data.error as keyof typeof TEST_ERRORS] ?? t('st.ai.modelsManual')} />}
        <FormLayout>
          <ModelField
            label={t('st.ai.primaryModel')}
            description={t('st.ai.primaryHint', { model: data.defaults.primary_model })}
            value={draft.primary_model}
            models={listed}
            onChange={(value) => setDraft({ ...draft, primary_model: value || data.defaults.primary_model })}
          />
          <ModelField
            label={t('st.ai.fallbackModel')}
            description={t('st.ai.fallbackHint')}
            value={draft.fallback_model}
            models={listed}
            allowNone
            onChange={(value) => setDraft({ ...draft, fallback_model: value })}
          />
        </FormLayout>
        <VStack gap={1.5}>
          <Text weight="semibold">{t('st.ai.reasoningTitle')}</Text>
          <SegmentedControl label={t('st.ai.reasoning')} value={draft.reasoning_effort} onChange={(value) => setDraft({ ...draft, reasoning_effort: value as ReasoningEffort })}>
            <SegmentedControlItem value="none" label={t('st.ai.effort.none')} />
            <SegmentedControlItem value="low" label={t('st.ai.effort.low')} />
            <SegmentedControlItem value="medium" label={t('st.ai.effort.medium')} />
            <SegmentedControlItem value="high" label={t('st.ai.effort.high')} />
          </SegmentedControl>
          <Text type="supporting">{t('st.ai.reasoningHint')}</Text>
        </VStack>
        <Slider
          label={t('st.ai.maxTokens')}
          description={t('st.ai.maxTokensHint')}
          value={draft.max_output_tokens}
          min={data.limits.min_output_tokens}
          max={data.limits.max_output_tokens}
          step={500}
          valueDisplay="text"
          onChange={(value: number) => setDraft({ ...draft, max_output_tokens: value })}
        />
        <Switch
          label={t('st.ai.webSearch')}
          description={t('st.ai.webSearchHint')}
          value={draft.web_search_enabled}
          onChange={(value) => setDraft({ ...draft, web_search_enabled: value })}
        />
        {draft.realtime_enabled !== undefined && <>
          <Divider />
          <Heading level={3}>{t('st.ai.voiceTitle')}</Heading>
          <Text type="supporting">{t('st.ai.voiceDesc')}</Text>
          <Switch
            label={t('st.ai.voiceCall')}
            description={t('st.ai.voiceCallHint')}
            value={draft.realtime_enabled}
            onChange={(value) => setDraft({ ...draft, realtime_enabled: value })}
          />
          {draft.voice_call_provider !== undefined && <Selector
            label={t('st.ai.engine')}
            description={t('st.ai.engineHint')}
            options={(data.voice_call_providers ?? ['auto', 'openai', 'chimege', 'elevenlabs']).map((value) => ({
              value,
              label: t(`st.ai.provider.${value}.label`),
              description: `${t(`st.ai.provider.${value}.description`)}${(value === 'chimege' && data.chimege && !data.chimege.voice_call_ready) || (value === 'elevenlabs' && data.elevenlabs && !data.elevenlabs.ready) ? ` · ${t('st.ai.source.none')}` : ''}`,
            }))}
            value={draft.voice_call_provider}
            onChange={(value) => setDraft({ ...draft, voice_call_provider: value as VoiceCallProvider })}
          />}
          <FormLayout>
            <ModelField
              label={t('st.ai.realtimeModel')}
              description={t('st.ai.realtimeHint', { model: data.defaults.realtime_model ?? 'gpt-realtime' })}
              value={draft.realtime_model ?? null}
              models={realtimeListed}
              onChange={(value) => setDraft({ ...draft, realtime_model: value || data.defaults.realtime_model || 'gpt-realtime' })}
            />
            <Selector
              label={t('st.ai.voice')}
              description={t('st.ai.voiceHint')}
              options={(data.realtime_voices ?? []).map((voice) => ({ value: voice, label: voice }))}
              value={draft.realtime_voice}
              onChange={(value) => setDraft({ ...draft, realtime_voice: value })}
            />
          </FormLayout>
        </>}
        <Divider />
        {testResult && (testResult.ok
          ? <Banner status="success" title={t('st.ai.testOk', { model: testResult.model })} description={`${t('st.ai.testLatency', { ms: testResult.latency_ms })}${testResult.model_listed === false ? ` · ${t('st.ai.testNotListed')}` : ''}`} isDismissable onDismiss={() => setTestResult(null)} />
          : <Banner status="error" title={t('st.ai.connectionFailed')} description={TEST_ERRORS[(testResult.error ?? '') as keyof typeof TEST_ERRORS] ?? testResult.error ?? t('st.ai.unknownError')} isDismissable onDismiss={() => setTestResult(null)} />)}
        <HStack gap={2} vAlign="center" wrap="wrap">
          <Button label={t('st.common.save')} variant="primary" isDisabled={!dirty} isLoading={update.isPending} clickAction={save} />
          <Button label={t('st.ai.testConnection')} isLoading={testConnection.isPending} clickAction={runTest} />
          <StatusDot variant={data.key_source === 'none' ? 'error' : 'success'} label={data.key_source === 'none' ? t('st.ai.disabled') : t('st.ai.enabled')} />
          <Text type="supporting">{data.key_source === 'none' ? t('st.ai.noKeyHint') : t('st.ai.active')}</Text>
        </HStack>
      </VStack>
    </Card>

    {data.chimege && <ChimegeSettings settings={data.chimege} />}
    {data.elevenlabs && <ElevenLabsSettings settings={data.elevenlabs} />}
  </VStack>
}
