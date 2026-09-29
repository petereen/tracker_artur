import { useEffect, useState } from 'react'
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

const SOURCE: Record<ChimegeTokenState['source'], { label: string; color: 'green' | 'blue' | 'red' }> = {
  organization: { label: 'Байгууллагын token', color: 'green' },
  environment: { label: 'Серверийн орчны token (env)', color: 'blue' },
  none: { label: 'Тохируулаагүй', color: 'red' },
}

const TEST_ERRORS: Record<string, string> = {
  not_configured: 'Token оруулаагүй байна.',
  needs_tts: 'Таних үйлчилгээг шалгахад TTS token хэрэгтэй (шалгалтын аудиог TTS-ээр үүсгэдэг).',
}

type Kind = 'stt' | 'tts'

function TokenField({ kind, state, value, onChange, onClear, busy }: {
  kind: Kind
  state: ChimegeTokenState
  value: string
  onChange: (value: string) => void
  onClear: () => void
  busy: boolean
}) {
  const source = SOURCE[state.source]
  const title = kind === 'stt' ? 'Яриа таних (STT) token' : 'Дуу үүсгэх (TTS) token'
  return <VStack gap={2}>
    <HStack gap={2} vAlign="center" wrap="wrap">
      <Text weight="semibold">{title}</Text>
      <Token size="sm" color={source.color} label={source.label} />
      {state.has_token && state.token_last4 && <Token size="sm" label={`…${state.token_last4}`} />}
    </HStack>
    <TextInput
      type="password"
      label={state.has_token ? `${title}: шинээр солих` : title}
      description="Хоосон орхивол одоогийн token хэвээр үлдэнэ."
      value={value}
      onChange={onChange}
      isOptional
    />
    {state.has_token && <HStack gap={2}>
      <Button label="Token устгах" variant="destructive" size="sm" isLoading={busy} onClick={() => { if (window.confirm(`${title}-ийг устгах уу?`)) onClear() }} />
    </HStack>}
  </VStack>
}

function testLine(label: string, result: ChimegeTestResult['stt'] | ChimegeTestResult['tts']) {
  if (result.ok) return `${label}: амжилттай${result.latency_ms != null ? ` (${result.latency_ms} мс)` : ''}`
  return `${label}: ${TEST_ERRORS[result.error ?? ''] ?? result.error ?? 'алдаа'}`
}

/** Chimege tokens and switches for Mongolian speech (Telegram voice, web, calls). */
export function ChimegeSettings({ settings }: { settings: Settings }) {
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
      setResult({ tts: { ok: false, error: 'Сервертэй холбогдож чадсангүй.' }, stt: { ok: false, error: 'Сервертэй холбогдож чадсангүй.' } })
    }
  }

  const callReadyAfterSave = draft.call && draft.stt && draft.tts
    && (settings.stt.source !== 'none' || Boolean(tokens.stt.trim()))
    && (settings.tts.source !== 'none' || Boolean(tokens.tts.trim()))

  return <Card padding={5}>
    <VStack gap={4}>
      <Heading level={3}>Chimege · Монгол яриа</Heading>
      <Text type="supporting">Chimege нь монгол яриаг таньж, монгол дуу хоолойгоор уншина. Telegram-ын дуут мессеж, вэбийн дуу оруулалт болон монгол хэлний дуут дуудлагад ашиглана. Token-ийг шифрлэж хадгална; хадгалсны дараа дахин харуулахгүй.</Text>
      <FormLayout>
        <TokenField kind="stt" state={settings.stt} value={tokens.stt} onChange={(value) => setTokens({ ...tokens, stt: value })} onClear={() => update.mutate({ clear_chimege_stt_token: true })} busy={update.isPending} />
        <TokenField kind="tts" state={settings.tts} value={tokens.tts} onChange={(value) => setTokens({ ...tokens, tts: value })} onClear={() => update.mutate({ clear_chimege_tts_token: true })} busy={update.isPending} />
      </FormLayout>
      <Divider />
      <Switch
        label="Chimege яриа таних"
        description="Дуут мессеж, дуу оруулалтыг эхлээд Chimege-ээр таньна. Идэвхгүй эсвэл алдаатай үед OpenAI ашиглана."
        value={draft.stt}
        onChange={(value) => setDraft({ ...draft, stt: value })}
      />
      <Switch
        label="Chimege дуу хоолой"
        description="OYUNS-ийн хариултыг Chimege-ийн монгол дуу хоолойгоор уншина (Telegram дуут хариулт, дуудлага)."
        value={draft.tts}
        onChange={(value) => setDraft({ ...draft, tts: value })}
      />
      <Switch
        label="Монгол хэлний дуудлагад Chimege ашиглах"
        description="Интерфейсийн хэл монгол үед дуут дуудлага Chimege таних → OYUNS → Chimege дуу хоолойгоор явагдана. Хариулт бага зэрэг удаан ч монгол хэлийг хамаагүй сайн ойлгож, зөв дуудна. Идэвхгүй бол OpenAI Realtime ашиглана."
        value={draft.call}
        onChange={(value) => setDraft({ ...draft, call: value })}
      />
      {draft.call && !callReadyAfterSave && <Banner status="warning" title="Монгол горим ажиллахгүй" description="Монгол хэлний дуудлагад таних ба дуу үүсгэх хоёр token хоёулаа тохируулагдаж, хоёр шилжүүлэгч идэвхтэй байх шаардлагатай. Одоогоор OpenAI Realtime ашиглагдана." />}
      {result && <Banner
        status={result.tts.ok && result.stt.ok ? 'success' : result.tts.ok || result.stt.ok ? 'warning' : 'error'}
        title="Chimege шалгалт"
        description={`${testLine('Дуу үүсгэх', result.tts)} · ${testLine('Яриа таних', result.stt)}${result.stt.transcript ? ` — «${result.stt.transcript}»` : ''}`}
        isDismissable
        onDismiss={() => setResult(null)}
      />}
      <HStack gap={2} vAlign="center" wrap="wrap">
        <Button label="Chimege хадгалах" variant="primary" isDisabled={!dirty} isLoading={update.isPending} clickAction={save} />
        <Button label="Chimege шалгах" isLoading={test.isPending} clickAction={runTest} />
      </HStack>
    </VStack>
  </Card>
}
