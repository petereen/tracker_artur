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
import { ChimegeSettings } from './ChimegeSettings'
import { ElevenLabsSettings } from './ElevenLabsSettings'

const CUSTOM = '__custom__'
const NO_FALLBACK = '__none__'

const VOICE_PROVIDERS: Record<VoiceCallProvider, { label: string; description: string }> = {
  auto: { label: 'Автомат', description: 'Монгол хэлэнд Chimege (тохируулсан бол), бусад хэлэнд OpenAI Realtime.' },
  openai: { label: 'OpenAI Realtime', description: 'Шууд яриа, хамгийн бага хоцролт; монгол хэл сул.' },
  chimege: { label: 'Chimege', description: 'Зөвхөн монгол хэл; ээлжээр хариулна.' },
  elevenlabs: { label: 'ElevenLabs', description: 'Урсгал дуу (streaming TTS) + Scribe таних; англи, орос хэлэнд хамгийн байгалийн.' },
}

const SOURCE_LABEL: Record<Settings['key_source'], { label: string; color: 'green' | 'blue' | 'red' }> = {
  organization: { label: 'Байгууллагын түлхүүр', color: 'green' },
  environment: { label: 'Серверийн орчны түлхүүр (env)', color: 'blue' },
  none: { label: 'Тохируулаагүй', color: 'red' },
}

const TEST_ERRORS: Record<string, string> = {
  invalid_key: 'API түлхүүр хүчингүй байна.',
  forbidden: 'Энэ түлхүүрт тухайн моделийг ашиглах эрх алга.',
  model_not_found: 'Модель олдсонгүй. Моделийн нэрийг шалгана уу.',
  rate_limited: 'OpenAI хязгаар/төлбөрийн лимит хүрсэн байна.',
  not_configured: 'API түлхүүр оруулаагүй байна.',
  network: 'OpenAI-тай холбогдож чадсангүй.',
  provider_error: 'OpenAI талд алдаа гарлаа. Дахин оролдоно уу.',
  rejected: 'OpenAI хүсэлтийг хүлээж авсангүй.',
}

function modelOptions(models: string[], ...current: (string | null | undefined)[]) {
  const values = Array.from(new Set([...current.filter((item): item is string => Boolean(item)), ...models]))
  return [...values.map((value) => ({ value, label: value })), { type: 'divider' as const }, { value: CUSTOM, label: 'Өөр модель (гараар оруулах)' }]
}

function ModelField({ label, description, value, models, onChange, allowNone }: {
  label: string
  description: string
  value: string | null
  models: string[]
  onChange: (value: string | null) => void
  allowNone?: boolean
}) {
  const [custom, setCustom] = useState(false)
  const options = useMemo(() => {
    const base = modelOptions(models, value)
    return allowNone ? [{ value: NO_FALLBACK, label: 'Нөөц модельгүй' }, ...base] : base
  }, [models, value, allowNone])
  return <VStack gap={2}>
    <Selector
      label={label}
      description={description}
      options={options}
      value={custom ? CUSTOM : value ?? (allowNone ? NO_FALLBACK : undefined)}
      hasSearch
      searchPlaceholder="Модель хайх…"
      onChange={(next) => {
        if (next === CUSTOM) { setCustom(true); return }
        setCustom(false)
        onChange(next === NO_FALLBACK ? null : next)
      }}
    />
    {custom && <TextInput label={`${label}: моделийн ID`} description="Жишээ: gpt-5-mini, gpt-4.1" value={value ?? ''} onChange={(next) => onChange(next.trim() || null)} />}
  </VStack>
}

export function AiAgentSettings() {
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

  if (settings.isLoading || !draft) return <Text type="supporting">AI тохиргоог ачаалж байна…</Text>
  if (settings.isError || !settings.data) return <Banner status="error" title="AI тохиргоог ачаалж чадсангүй" />

  const data = settings.data
  const source = SOURCE_LABEL[data.key_source]
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
          <Heading level={3}>OpenAI API түлхүүр</Heading>
          <Token size="sm" color={source.color} label={source.label} />
          {data.has_key && data.key_last4 && <Token size="sm" label={`sk-…${data.key_last4}`} />}
        </HStack>
        <Text type="supporting">Түлхүүрийг шифрлэж хадгална; хадгалсны дараа дахин харуулахгүй. Байгууллагын түлхүүр серверийн орчны түлхүүрээс давуу эрэмбэтэй.</Text>
        <TextInput
          type="password"
          label={data.has_key ? 'Шинэ түлхүүрээр солих' : 'API түлхүүр'}
          description="sk-… хэлбэртэй. Хоосон орхивол одоогийн түлхүүр хэвээр үлдэнэ."
          value={apiKey}
          onChange={setApiKey}
          isOptional={data.key_source !== 'none'}
        />
        {data.has_key && <HStack gap={2}>
          <Button label="Байгууллагын түлхүүрийг устгах" variant="destructive" size="sm" isLoading={update.isPending} onClick={() => { if (window.confirm('Байгууллагын API түлхүүрийг устгах уу?')) update.mutate({ clear_api_key: true }) }} />
        </HStack>}
      </VStack>
    </Card>

    <Card padding={5}>
      <VStack gap={4}>
        <Heading level={3}>Модель ба хариултын тохиргоо</Heading>
        {models.data?.error && <Banner status="warning" title="Моделийн жагсаалтыг татаж чадсангүй" description={TEST_ERRORS[models.data.error] ?? 'Моделийн ID-г гараар оруулж болно.'} />}
        <FormLayout>
          <ModelField
            label="Үндсэн модель"
            description={`Бүх OYUNS хариултыг энэ модель боловсруулна. Анхдагч: ${data.defaults.primary_model}`}
            value={draft.primary_model}
            models={listed}
            onChange={(value) => setDraft({ ...draft, primary_model: value || data.defaults.primary_model })}
          />
          <ModelField
            label="Нөөц модель"
            description="Үндсэн модель ажиллахгүй үед автоматаар ашиглана."
            value={draft.fallback_model}
            models={listed}
            allowNone
            onChange={(value) => setDraft({ ...draft, fallback_model: value })}
          />
        </FormLayout>
        <VStack gap={1.5}>
          <Text weight="semibold">Сэтгэх түвшин (reasoning)</Text>
          <SegmentedControl label="Сэтгэх түвшин" value={draft.reasoning_effort} onChange={(value) => setDraft({ ...draft, reasoning_effort: value as ReasoningEffort })}>
            <SegmentedControlItem value="none" label="Хамгийн хурдан" />
            <SegmentedControlItem value="low" label="Хурдан" />
            <SegmentedControlItem value="medium" label="Дунд" />
            <SegmentedControlItem value="high" label="Гүнзгий" />
          </SegmentedControl>
          <Text type="supporting">Зөвхөн reasoning дэмждэг модельд (gpt-5, o-цуврал) хамаарна. Гүнзгий нь удаан, илүү үнэтэй.</Text>
        </VStack>
        <Slider
          label="Хариултын дээд урт (token)"
          description="Урт тайлан, дүгнэлтэд илүү их token хэрэгтэй."
          value={draft.max_output_tokens}
          min={data.limits.min_output_tokens}
          max={data.limits.max_output_tokens}
          step={500}
          valueDisplay="text"
          onChange={(value: number) => setDraft({ ...draft, max_output_tokens: value })}
        />
        <Switch
          label="Вэб хайлт"
          description="Компанийн бус, олон нийтийн шинэ мэдээлэлд (мэдээ, үнэ) вэб хайлт ашиглахыг зөвшөөрөх."
          value={draft.web_search_enabled}
          onChange={(value) => setDraft({ ...draft, web_search_enabled: value })}
        />
        {draft.realtime_enabled !== undefined && <>
          <Divider />
          <Heading level={3}>Дуут дуудлага (Realtime)</Heading>
          <Text type="supporting">Чат дахь OYUNS Agent руу залгахад OYUNS шууд ярьж, компанийн мэдлэг ба өгөгдлийг хэрэглэгчийн эрхийн хүрээнд уншина. Хөдөлгүүр: OpenAI Realtime, Chimege эсвэл ElevenLabs.</Text>
          <Switch
            label="Дуут дуудлага"
            description="Идэвхгүй бол чат дахь OYUNS Agent-ийн дуудлагын товч ажиллахгүй."
            value={draft.realtime_enabled}
            onChange={(value) => setDraft({ ...draft, realtime_enabled: value })}
          />
          {draft.voice_call_provider !== undefined && <Selector
            label="Дуудлагын хөдөлгүүр"
            description="Дуудлага аль үйлчилгээгээр явагдахыг сонгоно. Хэрэглэгч дуудлагын цонхноос тохируулсан бусад хөдөлгүүр рүү шилжиж болно; бэлэн бус хөдөлгүүр сонгосон бол автомат горимд шилжинэ."
            options={(data.voice_call_providers ?? ['auto', 'openai', 'chimege', 'elevenlabs']).map((value) => ({
              value,
              label: VOICE_PROVIDERS[value].label,
              description: `${VOICE_PROVIDERS[value].description}${(value === 'chimege' && data.chimege && !data.chimege.voice_call_ready) || (value === 'elevenlabs' && data.elevenlabs && !data.elevenlabs.ready) ? ' · Тохируулаагүй' : ''}`,
            }))}
            value={draft.voice_call_provider}
            onChange={(value) => setDraft({ ...draft, voice_call_provider: value as VoiceCallProvider })}
          />}
          <FormLayout>
            <ModelField
              label="Realtime модель"
              description={`Анхдагч: ${data.defaults.realtime_model ?? 'gpt-realtime'} (OpenAI-ийн хамгийн сүүлийн realtime модель)`}
              value={draft.realtime_model ?? null}
              models={realtimeListed}
              onChange={(value) => setDraft({ ...draft, realtime_model: value || data.defaults.realtime_model || 'gpt-realtime' })}
            />
            <Selector
              label="Дуу хоолой"
              description="OYUNS-ийн ярих дуу"
              options={(data.realtime_voices ?? []).map((voice) => ({ value: voice, label: voice }))}
              value={draft.realtime_voice}
              onChange={(value) => setDraft({ ...draft, realtime_voice: value })}
            />
          </FormLayout>
        </>}
        <Divider />
        {testResult && (testResult.ok
          ? <Banner status="success" title={`Холболт амжилттай: ${testResult.model}`} description={`Хариу өгөх хугацаа ${testResult.latency_ms} мс${testResult.model_listed === false ? ' · модель жагсаалтад харагдахгүй байгаа ч хариулсан' : ''}`} isDismissable onDismiss={() => setTestResult(null)} />
          : <Banner status="error" title="Холболт амжилтгүй" description={TEST_ERRORS[testResult.error ?? ''] ?? testResult.error ?? 'Тодорхойгүй алдаа'} isDismissable onDismiss={() => setTestResult(null)} />)}
        <HStack gap={2} vAlign="center" wrap="wrap">
          <Button label="Хадгалах" variant="primary" isDisabled={!dirty} isLoading={update.isPending} clickAction={save} />
          <Button label="Холболт шалгах" isLoading={testConnection.isPending} clickAction={runTest} />
          <StatusDot variant={data.key_source === 'none' ? 'error' : 'success'} label={data.key_source === 'none' ? 'AI идэвхгүй' : 'AI идэвхтэй'} />
          <Text type="supporting">{data.key_source === 'none' ? 'API түлхүүргүй үед OYUNS зөвхөн баримт бичгээс шууд хайлт хийнэ.' : 'OYUNS идэвхтэй.'}</Text>
        </HStack>
      </VStack>
    </Card>

    {data.chimege && <ChimegeSettings settings={data.chimege} />}
    {data.elevenlabs && <ElevenLabsSettings settings={data.elevenlabs} />}
  </VStack>
}
