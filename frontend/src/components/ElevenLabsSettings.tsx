import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { labelMap } from '../utils/labelMap'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { Divider } from '@astryxdesign/core/Divider'
import { FormLayout } from '@astryxdesign/core/FormLayout'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { Selector } from '@astryxdesign/core/Selector'
import { Switch } from '@astryxdesign/core/Switch'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  type ElevenLabsSettings as Settings,
  type ElevenLabsTestResult,
  useElevenLabsVoices,
  useTestElevenLabs,
  useUpdateAiAgentSettings,
} from '../api/aiSettings'

const CUSTOM = '__custom__'

const SOURCE_COLORS: Record<Settings['source'], 'green' | 'blue' | 'red'> = { organization: 'green', environment: 'blue', none: 'red' }
const MODEL_LABELS = labelMap('st.el.model', ['eleven_flash_v2_5', 'eleven_turbo_v2_5', 'eleven_multilingual_v2'])
const ERRORS = labelMap('st.el.error', ['not_configured', 'invalid_key', 'forbidden', 'rate_limited', 'network', 'provider_error', 'rejected'])

/** ElevenLabs key, voice and model for streamed voice-call speech. */
export function ElevenLabsSettings({ settings }: { settings: Settings }) {
  const { t } = useTranslation()
  const update = useUpdateAiAgentSettings()
  const test = useTestElevenLabs()
  const voices = useElevenLabsVoices(settings.source !== 'none')
  const [apiKey, setApiKey] = useState('')
  const [draft, setDraft] = useState({ enabled: settings.enabled, voice_id: settings.voice_id, model: settings.model })
  const [custom, setCustom] = useState(false)
  const [result, setResult] = useState<ElevenLabsTestResult | null>(null)

  useEffect(() => {
    setDraft({ enabled: settings.enabled, voice_id: settings.voice_id, model: settings.model })
  }, [settings])

  const voiceOptions = useMemo(() => {
    const listed = voices.data?.voices ?? []
    const options = listed.map((voice) => ({ value: voice.voice_id, label: voice.name, description: voice.description ?? voice.category ?? undefined }))
    if (!listed.some((voice) => voice.voice_id === draft.voice_id)) options.unshift({ value: draft.voice_id, label: draft.voice_id, description: draft.voice_id === settings.default_voice_id ? t('st.el.defaultVoice') : t('st.el.manualId') })
    return [...options, { type: 'divider' as const }, { value: CUSTOM, label: t('st.el.otherVoice') }]
  }, [voices.data, draft.voice_id, settings.default_voice_id, t])

  const dirty = Boolean(apiKey.trim()) || draft.enabled !== settings.enabled || draft.voice_id !== settings.voice_id || draft.model !== settings.model
  const source = { label: t(`st.ai.source.${settings.source}`), color: SOURCE_COLORS[settings.source] }

  const save = async () => {
    try {
      await update.mutateAsync({
        elevenlabs_api_key: apiKey.trim() || null,
        elevenlabs_enabled: draft.enabled,
        elevenlabs_voice_id: draft.voice_id,
        elevenlabs_model: draft.model,
      })
      setApiKey('')
      setCustom(false)
    } catch { /* the mutation's onError shows the toast */ }
  }

  const runTest = async () => {
    try {
      setResult(await test.mutateAsync({ api_key: apiKey.trim() || null }))
    } catch {
      setResult({ ok: false, error: 'network', latency_ms: null, voices: 0 })
    }
  }

  return <Card padding={5}>
    <VStack gap={4}>
      <HStack gap={2} vAlign="center" wrap="wrap">
        <Heading level={3}>{t('st.el.title')}</Heading>
        <Token size="sm" color={source.color} label={source.label} />
        {settings.has_key && settings.key_last4 && <Token size="sm" label={`…${settings.key_last4}`} />}
      </HStack>
      <Text type="supporting">{t('st.el.intro')}</Text>
      <TextInput
        type="password"
        label={settings.has_key ? t('st.el.replaceKey') : t('st.el.apiKey')}
        description={t('st.el.keyHint')}
        value={apiKey}
        onChange={setApiKey}
        isOptional
      />
      {settings.has_key && <HStack gap={2}>
        <Button label={t('st.el.deleteKey')} variant="destructive" size="sm" isLoading={update.isPending} onClick={() => { if (window.confirm(t('st.el.deleteConfirm'))) update.mutate({ clear_elevenlabs_api_key: true }) }} />
      </HStack>}
      <Divider />
      {voices.data?.error && voices.data.error !== 'not_configured' && <Banner status="warning" title={t('st.el.voicesFailed')} description={ERRORS[voices.data.error as keyof typeof ERRORS] ?? t('st.el.voiceIdManual')} />}
      <FormLayout>
        <VStack gap={2}>
          <Selector
            label={t('st.ai.voice')}
            description={t('st.el.voicesHint')}
            options={voiceOptions}
            value={custom ? CUSTOM : draft.voice_id}
            hasSearch
            searchPlaceholder={t('st.el.searchVoice')}
            onChange={(next) => {
              if (next === CUSTOM) { setCustom(true); return }
              setCustom(false)
              setDraft({ ...draft, voice_id: next })
            }}
          />
          {custom && <TextInput label="Voice ID" description={t('st.el.voiceIdHint')} value={draft.voice_id} onChange={(next) => setDraft({ ...draft, voice_id: next.trim() })} />}
        </VStack>
        <Selector
          label={t('st.el.model')}
          description={t('st.el.modelHint')}
          options={settings.models.map((model) => ({ value: model, label: MODEL_LABELS[model as keyof typeof MODEL_LABELS] ?? model }))}
          value={draft.model}
          onChange={(next) => setDraft({ ...draft, model: next })}
        />
      </FormLayout>
      <Switch
        label={t('st.el.use')}
        description={t('st.el.useHint')}
        value={draft.enabled}
        onChange={(value) => setDraft({ ...draft, enabled: value })}
      />
      {result && (result.ok
        ? <Banner status="success" title={t('st.el.testOk')} description={t('st.el.testOkLine', { voices: result.voices, ms: result.latency_ms })} isDismissable onDismiss={() => setResult(null)} />
        : <Banner status="error" title={t('st.el.testFailed')} description={ERRORS[(result.error ?? '') as keyof typeof ERRORS] ?? result.error ?? t('st.ai.unknownError')} isDismissable onDismiss={() => setResult(null)} />)}
      <HStack gap={2} vAlign="center" wrap="wrap">
        <Button label={t('st.el.saveBtn')} variant="primary" isDisabled={!dirty} isLoading={update.isPending} clickAction={save} />
        <Button label={t('st.el.testBtn')} isLoading={test.isPending} clickAction={runTest} />
      </HStack>
    </VStack>
  </Card>
}
