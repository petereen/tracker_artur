import { useEffect, useMemo, useState } from 'react'
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

const SOURCE: Record<Settings['source'], { label: string; color: 'green' | 'blue' | 'red' }> = {
  organization: { label: 'Байгууллагын түлхүүр', color: 'green' },
  environment: { label: 'Серверийн орчны түлхүүр (env)', color: 'blue' },
  none: { label: 'Тохируулаагүй', color: 'red' },
}

const MODEL_LABELS: Record<string, string> = {
  eleven_flash_v2_5: 'Flash v2.5 — хамгийн хурдан (~75 мс)',
  eleven_turbo_v2_5: 'Turbo v2.5 — хурдан, илүү чанартай',
  eleven_multilingual_v2: 'Multilingual v2 — хамгийн чанартай, удаан',
}

const ERRORS: Record<string, string> = {
  not_configured: 'API түлхүүр оруулаагүй байна.',
  invalid_key: 'ElevenLabs API түлхүүр хүчингүй байна.',
  forbidden: 'Түлхүүрт дуу үүсгэх (Text to Speech) эрх алга.',
  rate_limited: 'ElevenLabs-ийн лимит/кредит дууссан байна.',
  network: 'ElevenLabs-тай холбогдож чадсангүй.',
  provider_error: 'ElevenLabs талд алдаа гарлаа. Дахин оролдоно уу.',
  rejected: 'ElevenLabs хүсэлтийг хүлээж авсангүй.',
}

/** ElevenLabs key, voice and model for streamed voice-call speech. */
export function ElevenLabsSettings({ settings }: { settings: Settings }) {
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
    if (!listed.some((voice) => voice.voice_id === draft.voice_id)) options.unshift({ value: draft.voice_id, label: draft.voice_id, description: draft.voice_id === settings.default_voice_id ? 'Sarah (анхдагч)' : 'Гараар оруулсан ID' })
    return [...options, { type: 'divider' as const }, { value: CUSTOM, label: 'Өөр дуу (voice ID гараар)' }]
  }, [voices.data, draft.voice_id, settings.default_voice_id])

  const dirty = Boolean(apiKey.trim()) || draft.enabled !== settings.enabled || draft.voice_id !== settings.voice_id || draft.model !== settings.model
  const source = SOURCE[settings.source]

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
        <Heading level={3}>ElevenLabs · Realtime дуу хоолой</Heading>
        <Token size="sm" color={source.color} label={source.label} />
        {settings.has_key && settings.key_last4 && <Token size="sm" label={`…${settings.key_last4}`} />}
      </HStack>
      <Text type="supporting">ElevenLabs нь OYUNS-ийн хариултыг WebSocket-оор шууд урсгаж (streaming) уншина, ярианы таних хэсэгт Scribe ашиглана. Англи, орос хэлэнд маш байгалийн; монгол хэлийг албан ёсоор дэмждэггүй тул монгол дуудлагад Chimege илүү тохиромжтой. Түлхүүр шифрлэгдэж хадгалагдана; хөтөч рүү зөвхөн нэг удаагийн token очно.</Text>
      <TextInput
        type="password"
        label={settings.has_key ? 'ElevenLabs API түлхүүр: шинээр солих' : 'ElevenLabs API түлхүүр'}
        description="Хоосон орхивол одоогийн түлхүүр хэвээр үлдэнэ. Text to Speech ба Speech to Text эрхтэй түлхүүр хэрэгтэй."
        value={apiKey}
        onChange={setApiKey}
        isOptional
      />
      {settings.has_key && <HStack gap={2}>
        <Button label="Түлхүүр устгах" variant="destructive" size="sm" isLoading={update.isPending} onClick={() => { if (window.confirm('ElevenLabs API түлхүүрийг устгах уу?')) update.mutate({ clear_elevenlabs_api_key: true }) }} />
      </HStack>}
      <Divider />
      {voices.data?.error && voices.data.error !== 'not_configured' && <Banner status="warning" title="Дууны жагсаалтыг татаж чадсангүй" description={ERRORS[voices.data.error] ?? 'Voice ID-г гараар оруулж болно.'} />}
      <FormLayout>
        <VStack gap={2}>
          <Selector
            label="Дуу хоолой"
            description="Таны ElevenLabs бүртгэлд байгаа дуунууд"
            options={voiceOptions}
            value={custom ? CUSTOM : draft.voice_id}
            hasSearch
            searchPlaceholder="Дуу хайх…"
            onChange={(next) => {
              if (next === CUSTOM) { setCustom(true); return }
              setCustom(false)
              setDraft({ ...draft, voice_id: next })
            }}
          />
          {custom && <TextInput label="Voice ID" description="ElevenLabs → Voices → ID хуулах" value={draft.voice_id} onChange={(next) => setDraft({ ...draft, voice_id: next.trim() })} />}
        </VStack>
        <Selector
          label="Модель"
          description="Дуудлагад хурд чухал тул Flash v2.5-г зөвлөж байна."
          options={settings.models.map((model) => ({ value: model, label: MODEL_LABELS[model] ?? model }))}
          value={draft.model}
          onChange={(next) => setDraft({ ...draft, model: next })}
        />
      </FormLayout>
      <Switch
        label="ElevenLabs ашиглах"
        description="Идэвхгүй бол дуудлагын хөдөлгүүрийн сонголтод ElevenLabs харагдахгүй."
        value={draft.enabled}
        onChange={(value) => setDraft({ ...draft, enabled: value })}
      />
      {result && (result.ok
        ? <Banner status="success" title="ElevenLabs холболт амжилттай" description={`${result.voices} дуу олдлоо · ${result.latency_ms} мс`} isDismissable onDismiss={() => setResult(null)} />
        : <Banner status="error" title="ElevenLabs холболт амжилтгүй" description={ERRORS[result.error ?? ''] ?? result.error ?? 'Тодорхойгүй алдаа'} isDismissable onDismiss={() => setResult(null)} />)}
      <HStack gap={2} vAlign="center" wrap="wrap">
        <Button label="ElevenLabs хадгалах" variant="primary" isDisabled={!dirty} isLoading={update.isPending} clickAction={save} />
        <Button label="ElevenLabs шалгах" isLoading={test.isPending} clickAction={runTest} />
      </HStack>
    </VStack>
  </Card>
}
