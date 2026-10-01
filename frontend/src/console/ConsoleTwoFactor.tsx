import { type ReactNode, useState } from 'react'
import toast from 'react-hot-toast'
import { QRCodeSVG } from 'qrcode.react'
import { Copy, Download, KeyRound, ShieldCheck } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { CheckboxInput } from '@astryxdesign/core/CheckboxInput'
import { Grid } from '@astryxdesign/core/Grid'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import { type OperatorSession, consoleError, consoleErrorCode, useTwoFactorCode, useTwoFactorEnrolment } from './consoleApi'

interface StepProps {
  mfaToken: string
  /** The second factor passed: open the console. */
  onSession: (session: OperatorSession) => void
  /** Back to the password form (also when the 10-minute challenge expired). */
  onRestart: () => void
}

const isAppCode = (value: string) => /^\d{6}$/.test(value.replace(/\s/g, ''))

function codeError(error: unknown, onRestart: () => void) {
  const status = (error as { response?: { status?: number } })?.response?.status
  if (status === 401) {
    toast.error('Хугацаа дууссан. Дахин нэвтэрнэ үү.')
    onRestart()
  } else if (status === 423) {
    toast.error('Олон удаа буруу оруулсан тул бүртгэл 15 минут түгжигдлээ.')
    onRestart()
  } else if (consoleErrorCode(error) === 'invalid_code') {
    toast.error('Код буруу байна. Апп дээрх шинэ кодыг оруулна уу.')
  } else {
    toast.error(consoleError(error, 'Баталгаажуулж чадсангүй'))
  }
}

function SetupStep({ index, title, children }: { index: number; title: string; children: ReactNode }) {
  return <HStack gap={3} vAlign="start">
    <Token size="sm" label={String(index)} />
    <VStack gap={2}>
      <Text weight="semibold">{title}</Text>
      {children}
    </VStack>
  </HStack>
}

function RecoveryCodes({ codes, account, onContinue }: { codes: string[]; account: string; onContinue: () => void }) {
  const [saved, setSaved] = useState(false)
  const text = `OYUNS ERP · Операторын консол — нөөц кодууд (${account})\nКод бүрийг нэг л удаа ашиглана.\n\n${codes.join('\n')}\n`
  const copy = async () => {
    try { await navigator.clipboard.writeText(codes.join('\n')); toast.success('Хуулагдлаа') } catch { toast.error('Хуулж чадсангүй') }
  }
  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'oyuns-console-recovery-codes.txt'
    link.click()
    URL.revokeObjectURL(url)
  }
  return <VStack gap={4}>
    <VStack gap={1}>
      <Heading level={1}>Нөөц кодуудаа хадгална уу</Heading>
      <Text type="supporting">2 шатлалт нэвтрэлт идэвхжлээ. Утсаа гээсэн эсвэл апп-аа устгасан үед эдгээр кодын аль нэгээр нэвтэрнэ. Код бүр нэг удаа хүчинтэй.</Text>
    </VStack>
    <Banner status="warning" title="Эдгээр кодыг дахин харуулахгүй" description="Нууц үгийн менежер эсвэл аюулгүй газар хадгална уу." />
    <Grid columns={2} gap={2}>
      {codes.map((code) => <Text key={code} type="code">{code}</Text>)}
    </Grid>
    <HStack gap={2}>
      <Button label="Хуулах" variant="secondary" size="sm" icon={<Copy size={14} />} onClick={() => { void copy() }} />
      <Button label="Татах (.txt)" variant="secondary" size="sm" icon={<Download size={14} />} onClick={download} />
    </HStack>
    <CheckboxInput label="Нөөц кодуудаа аюулгүй газар хадгаллаа" value={saved} onChange={setSaved} />
    <Button label="Консол руу орох" variant="primary" isDisabled={!saved} onClick={onContinue} />
  </VStack>
}

/** First login: connect an authenticator app (QR + first code), then save the recovery codes. */
export function TwoFactorSetup({ mfaToken, onSession, onRestart }: StepProps) {
  const enrolment = useTwoFactorEnrolment(mfaToken)
  const enable = useTwoFactorCode('enable')
  const [code, setCode] = useState('')
  const [session, setSession] = useState<OperatorSession | null>(null)

  if (session) return <RecoveryCodes codes={session.recovery_codes ?? []} account={session.operator.email} onContinue={() => onSession(session)} />

  const submit = async () => {
    try {
      setSession(await enable.mutateAsync({ mfa_token: mfaToken, code: code.replace(/\s/g, '') }))
    } catch (error) {
      setCode('')
      codeError(error, onRestart)
    }
  }
  const copySecret = async () => {
    try { await navigator.clipboard.writeText(enrolment.data?.secret ?? ''); toast.success('Түлхүүр хуулагдлаа') } catch { toast.error('Хуулж чадсангүй') }
  }
  const data = enrolment.data
  return <form onSubmit={(event) => { event.preventDefault(); void submit() }}>
    <VStack gap={4}>
      <VStack gap={1}>
        <Heading level={1}>2 шатлалт нэвтрэлт тохируулах</Heading>
        <Text type="supporting">Операторын консолд нууц үгээс гадна утасны баталгаажуулах апп-ын код шаардлагатай. Нэг удаа тохируулна.</Text>
      </VStack>
      {enrolment.isError
        ? <Banner status="error" title="Тохиргоог эхлүүлж чадсангүй" description={consoleError(enrolment.error, 'Дахин нэвтэрч оролдоно уу.')} />
        : <VStack gap={4}>
          <SetupStep index={1} title="Баталгаажуулах апп суулгах">
            <Text type="supporting">Google Authenticator, Microsoft Authenticator, Authy, 1Password, Bitwarden зэрэг TOTP дэмждэг ямар ч апп тохирно.</Text>
          </SetupStep>
          <SetupStep index={2} title="QR кодыг уншуулах">
            <Text type="supporting">Апп дотроо «+» → «QR код уншуулах»-ыг сонгоод доорх кодыг уншуулна.</Text>
            {data
              // White quiet zone: the code has to stay scannable in the dark theme.
              ? <div style={{ background: '#fff', padding: 12, borderRadius: 8, width: 'fit-content', lineHeight: 0 }}>
                <QRCodeSVG value={data.otpauth_uri} size={176} level="M" title="2 шатлалт нэвтрэлтийн QR код" />
              </div>
              : <Skeleton width={200} height={200} />}
            <Text type="supporting">Уншуулж чадахгүй бол «Түлхүүр гараар оруулах»-ыг сонгож, бүртгэл: {data?.account ?? '…'}, төрөл: цагт суурилсан (TOTP), түлхүүр:</Text>
            <HStack gap={2} vAlign="center">
              <Text type="code">{data ? data.secret.replace(/(.{4})/g, '$1 ').trim() : '…'}</Text>
              <Button label="Түлхүүр хуулах" variant="ghost" size="sm" icon={<Copy size={14} />} isDisabled={!data} onClick={() => { void copySecret() }} />
            </HStack>
          </SetupStep>
          <SetupStep index={3} title="Апп дээр гарсан 6 оронтой кодыг оруулах">
            <TextInput label="Баталгаажуулах код" value={code} onChange={setCode} placeholder="000000" autoComplete="one-time-code" htmlName="one-time-code" isRequired hasAutoFocus />
          </SetupStep>
        </VStack>}
      <HStack gap={2} hAlign="end">
        <Button label="Буцах" variant="ghost" onClick={onRestart} />
        <Button label="Баталгаажуулж идэвхжүүлэх" variant="primary" type="submit" icon={<ShieldCheck size={14} />} isDisabled={!data || !isAppCode(code) || enable.isPending} />
      </HStack>
    </VStack>
  </form>
}

/** Every later login: a code from the app, or a one-time recovery code. */
export function TwoFactorVerify({ mfaToken, onSession, onRestart }: StepProps) {
  const verify = useTwoFactorCode('verify')
  const [code, setCode] = useState('')
  const [useRecovery, setUseRecovery] = useState(false)
  const ready = useRecovery ? code.trim().length >= 10 : isAppCode(code)
  const submit = async () => {
    try {
      const session = await verify.mutateAsync({ mfa_token: mfaToken, code: code.trim() })
      if (useRecovery && typeof session.recovery_codes_left === 'number') toast(`Нөөц код ашиглагдлаа. Үлдсэн: ${session.recovery_codes_left}`)
      onSession(session)
    } catch (error) {
      setCode('')
      codeError(error, onRestart)
    }
  }
  return <form onSubmit={(event) => { event.preventDefault(); void submit() }}>
    <VStack gap={4}>
      <VStack gap={1}>
        <Heading level={1}>2 шатлалт баталгаажуулалт</Heading>
        <Text type="supporting">{useRecovery
          ? 'Тохируулах үед хадгалсан нөөц кодуудын аль нэгийг оруулна уу. Код бүр нэг удаа хүчинтэй.'
          : 'Баталгаажуулах апп (Google Authenticator г.м.) дээрх «OYUNS ERP Console»-ын 6 оронтой кодыг оруулна уу.'}</Text>
      </VStack>
      {useRecovery
        ? <TextInput key="recovery" label="Нөөц код" value={code} onChange={setCode} placeholder="xxxxx-xxxxx" autoComplete="off" isRequired hasAutoFocus />
        : <TextInput key="app" label="Баталгаажуулах код" value={code} onChange={setCode} placeholder="000000" autoComplete="one-time-code" htmlName="one-time-code" isRequired hasAutoFocus />}
      <Button label="Баталгаажуулах" variant="primary" type="submit" isDisabled={!ready || verify.isPending} />
      <HStack gap={2} hAlign="between">
        <Button label="Буцах" variant="ghost" size="sm" onClick={onRestart} />
        <Button label={useRecovery ? 'Апп-ын код ашиглах' : 'Нөөц код ашиглах'} variant="ghost" size="sm" icon={<KeyRound size={14} />}
          onClick={() => { setCode(''); setUseRecovery(!useRecovery) }} />
      </HStack>
    </VStack>
  </form>
}
