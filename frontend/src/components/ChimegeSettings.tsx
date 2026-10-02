import { useEffect, useState } from 'react'
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
import { Switch } from '@astryxdesign/core/Switch'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  type ChimegeSettings as Settings,
  type ChimegeTestResult,
  type ChimegeTokenState,
  useTestChimege,
  useUpdateAiAgentSettings,
} from '../api/aiSettings'

const SOURCE_COLORS: Record<ChimegeTokenState['source'], 'green' | 'blue' | 'red'> = { organization: 'green', environment: 'blue', none: 'red' }
const SOURCE_KEYS: Record<ChimegeTokenState['source'], string> = { organization: 'st.chi.source.organization', environment: 'st.chi.source.environment', none: 'st.ai.source.none' }
const TEST_ERRORS = labelMap('st.chi.testError', ['not_configured', 'needs_tts'])

type Kind = 'stt' | 'tts'

function TokenField({ kind, state, value, onChange, onClear, busy }: {
  kind: Kind
  state: ChimegeTokenState
  value: string
  onChange: (value: string) => void
  onClear: () => void
  busy: boolean
}) {
  const { t } = useTranslation()
  const source = { label: t(SOURCE_KEYS[state.source]), color: SOURCE_COLORS[state.source] }
  const title = kind === 'stt' ? t('st.chi.sttTitle') : t('st.chi.ttsTitle')
  return <VStack gap={2}>
    <HStack gap={2} vAlign="center" wrap="wrap">
      <Text weight="semibold">{title}</Text>
      <Token size="sm" color={source.color} label={source.label} />
      {state.has_token && state.token_last4 && <Token size="sm" label={`…${state.token_last4}`} />}
    </HStack>
    <TextInput
      type="password"
      label={state.has_token ? t('st.chi.replaceToken', { title }) : title}
      description={t('st.chi.tokenKeepHint')}
      value={value}
      onChange={onChange}
      isOptional
    />
    {state.has_token && <HStack gap={2}>
      <Button label={t('st.chi.deleteToken')} variant="destructive" size="sm" isLoading={busy} onClick={() => { if (window.confirm(t('st.chi.deleteConfirm', { title }))) onClear() }} />
    </HStack>}
  </VStack>
}

function testLine(label: string, result: ChimegeTestResult['stt'] | ChimegeTestResult['tts']) {
  if (result.ok) return result.latency_ms != null ? i18n.t('st.chi.testOkMs', { label, ms: result.latency_ms }) : i18n.t('st.chi.testOk', { label })
  return `${label}: ${TEST_ERRORS[(result.error ?? '') as keyof typeof TEST_ERRORS] ?? result.error ?? i18n.t('st.chi.testError')}`
}

/** Chimege tokens and switches for Mongolian speech (Telegram voice, web, calls). */
export function ChimegeSettings({ settings }: { settings: Settings }) {
  const { t } = useTranslation()
  const update = useUpdateAiAgentSettings()
  const test = useTestChimege()
  const [tokens, setTokens] = useState({ stt: '', tts: '' })
  const [draft, setDraft] = useState({ stt: settings.stt.enabled, tts: settings.tts.enabled, call: settings.voice_call_enabled })
  const [result, setResult] = useState<ChimegeTestResult | null>(null)

  useEffect(() => {
    setDraft({ stt: settings.stt.enabled, tts: settings.tts.enabled, call: settings.voice_call_enabled })
  }, [settings])

  const dirty = Boolean(tokens.stt.trim() || tokens.tts.trim())
    || draft.stt !== settings.stt.enabled || draft.tts !== settings.tts.enabled || draft.call !== settings.voice_call_enabled

  const save = async () => {
    try {
      await update.mutateAsync({
        chimege_stt_token: tokens.stt.trim() || null,
        chimege_tts_token: tokens.tts.trim() || null,
        chimege_stt_enabled: draft.stt,
        chimege_tts_enabled: draft.tts,
        chimege_voice_call_enabled: draft.call,
      })
      setTokens({ stt: '', tts: '' })
    } catch { /* the mutation's onError shows the toast */ }
  }

  const runTest = async () => {
    try {
      setResult(await test.mutateAsync({ stt_token: tokens.stt.trim() || null, tts_token: tokens.tts.trim() || null }))
    } catch {
      setResult({ tts: { ok: false, error: t('st.chi.serverUnreachable') }, stt: { ok: false, error: t('st.chi.serverUnreachable') } })
    }
  }

  const callReadyAfterSave = draft.call && draft.stt && draft.tts
    && (settings.stt.source !== 'none' || Boolean(tokens.stt.trim()))
    && (settings.tts.source !== 'none' || Boolean(tokens.tts.trim()))

  return <Card padding={5}>
    <VStack gap={4}>
      <Heading level={3}>{t('st.chi.title')}</Heading>
      <Text type="supporting">{t('st.chi.intro')}</Text>
      <FormLayout>
        <TokenField kind="stt" state={settings.stt} value={tokens.stt} onChange={(value) => setTokens({ ...tokens, stt: value })} onClear={() => update.mutate({ clear_chimege_stt_token: true })} busy={update.isPending} />
        <TokenField kind="tts" state={settings.tts} value={tokens.tts} onChange={(value) => setTokens({ ...tokens, tts: value })} onClear={() => update.mutate({ clear_chimege_tts_token: true })} busy={update.isPending} />
      </FormLayout>
      <Divider />
      <Switch
        label={t('st.chi.sttSwitch')}
        description={t('st.chi.sttSwitchHint')}
        value={draft.stt}
        onChange={(value) => setDraft({ ...draft, stt: value })}
      />
      <Switch
        label={t('st.chi.ttsSwitch')}
        description={t('st.chi.ttsSwitchHint')}
        value={draft.tts}
        onChange={(value) => setDraft({ ...draft, tts: value })}
      />
      <Switch
        label={t('st.chi.callSwitch')}
        description={t('st.chi.callSwitchHint')}
        value={draft.call}
        onChange={(value) => setDraft({ ...draft, call: value })}
      />
      {draft.call && !callReadyAfterSave && <Banner status="warning" title={t('st.chi.notWorking')} description={t('st.chi.notWorkingHint')} />}
      {result && <Banner
        status={result.tts.ok && result.stt.ok ? 'success' : result.tts.ok || result.stt.ok ? 'warning' : 'error'}
        title={t('st.chi.testTitle')}
        description={`${testLine(t('st.chi.lineTts'), result.tts)} · ${testLine(t('st.chi.lineStt'), result.stt)}${result.stt.transcript ? ` — «${result.stt.transcript}»` : ''}`}
        isDismissable
        onDismiss={() => setResult(null)}
      />}
      <HStack gap={2} vAlign="center" wrap="wrap">
        <Button label={t('st.chi.saveBtn')} variant="primary" isDisabled={!dirty} isLoading={update.isPending} clickAction={save} />
        <Button label={t('st.chi.testBtn')} isLoading={test.isPending} clickAction={runTest} />
      </HStack>
    </VStack>
  </Card>
}
