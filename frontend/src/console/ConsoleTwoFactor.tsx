import { type ReactNode, useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
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
    toast.error(i18n.t('con.tf.expired'))
    onRestart()
  } else if (status === 423) {
    toast.error(i18n.t('con.tf.locked'))
    onRestart()
  } else if (consoleErrorCode(error) === 'invalid_code') {
    toast.error(i18n.t('con.tf.invalidCode'))
  } else {
    toast.error(consoleError(error, i18n.t('con.tf.verifyFailed')))
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
  const { t } = useTranslation()
  const [saved, setSaved] = useState(false)
  const text = `${t('con.tf.fileHeader', { account })}\n${t('con.tf.fileNote')}\n\n${codes.join('\n')}\n`
  const copy = async () => {
    try { await navigator.clipboard.writeText(codes.join('\n')); toast.success(t('con.tf.copied')) } catch { toast.error(t('con.tf.copyFailed')) }
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
      <Heading level={1}>{t('con.tf.saveCodes')}</Heading>
      <Text type="supporting">{t('con.tf.enabled')}</Text>
    </VStack>
    <Banner status="warning" title={t('con.tf.noRepeat')} description={t('con.tf.keepSafe')} />
    <Grid columns={2} gap={2}>
      {codes.map((code) => <Text key={code} type="code">{code}</Text>)}
    </Grid>
    <HStack gap={2}>
      <Button label={t('con.tf.copy')} variant="secondary" size="sm" icon={<Copy size={14} />} onClick={() => { void copy() }} />
      <Button label={t('con.tf.download')} variant="secondary" size="sm" icon={<Download size={14} />} onClick={download} />
    </HStack>
    <CheckboxInput label={t('con.tf.saved')} value={saved} onChange={setSaved} />
    <Button label={t('con.tf.enter')} variant="primary" isDisabled={!saved} onClick={onContinue} />
  </VStack>
}

/** First login: connect an authenticator app (QR + first code), then save the recovery codes. */
export function TwoFactorSetup({ mfaToken, onSession, onRestart }: StepProps) {
  const { t } = useTranslation()
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
    try { await navigator.clipboard.writeText(enrolment.data?.secret ?? ''); toast.success(t('con.tf.keyCopied')) } catch { toast.error(t('con.tf.copyFailed')) }
  }
  const data = enrolment.data
  return <form onSubmit={(event) => { event.preventDefault(); void submit() }}>
    <VStack gap={4}>
      <VStack gap={1}>
        <Heading level={1}>{t('con.tf.setupTitle')}</Heading>
        <Text type="supporting">{t('con.tf.setupIntro')}</Text>
      </VStack>
      {enrolment.isError
        ? <Banner status="error" title={t('con.tf.setupFailed')} description={consoleError(enrolment.error, t('con.tf.tryAgain'))} />
        : <VStack gap={4}>
          <SetupStep index={1} title={t('con.tf.step1')}>
            <Text type="supporting">{t('con.tf.step1Text')}</Text>
          </SetupStep>
          <SetupStep index={2} title={t('con.tf.step2')}>
            <Text type="supporting">{t('con.tf.step2Text')}</Text>
            {data
              // White quiet zone: the code has to stay scannable in the dark theme.
              ? <div style={{ background: '#fff', padding: 12, borderRadius: 8, width: 'fit-content', lineHeight: 0 }}>
                <QRCodeSVG value={data.otpauth_uri} size={176} level="M" title={t('con.tf.qrTitle')} />
              </div>
              : <Skeleton width={200} height={200} />}
            <Text type="supporting">{t('con.tf.manual', { account: data?.account ?? '…' })}</Text>
            <HStack gap={2} vAlign="center">
              <Text type="code">{data ? data.secret.replace(/(.{4})/g, '$1 ').trim() : '…'}</Text>
              <Button label={t('con.tf.copyKey')} variant="ghost" size="sm" icon={<Copy size={14} />} isDisabled={!data} onClick={() => { void copySecret() }} />
            </HStack>
          </SetupStep>
          <SetupStep index={3} title={t('con.tf.step3')}>
            <TextInput label={t('con.tf.code')} value={code} onChange={setCode} placeholder="000000" autoComplete="one-time-code" htmlName="one-time-code" isRequired hasAutoFocus />
          </SetupStep>
        </VStack>}
      <HStack gap={2} hAlign="end">
        <Button label={t('con.tf.back')} variant="ghost" onClick={onRestart} />
        <Button label={t('con.tf.enable')} variant="primary" type="submit" icon={<ShieldCheck size={14} />} isDisabled={!data || !isAppCode(code) || enable.isPending} />
      </HStack>
    </VStack>
  </form>
}

/** Every later login: a code from the app, or a one-time recovery code. */
export function TwoFactorVerify({ mfaToken, onSession, onRestart }: StepProps) {
  const { t } = useTranslation()
  const verify = useTwoFactorCode('verify')
  const [code, setCode] = useState('')
  const [useRecovery, setUseRecovery] = useState(false)
  const ready = useRecovery ? code.trim().length >= 10 : isAppCode(code)
  const submit = async () => {
    try {
      const session = await verify.mutateAsync({ mfa_token: mfaToken, code: code.trim() })
      if (useRecovery && typeof session.recovery_codes_left === 'number') toast(t('con.tf.recoveryUsed', { n: session.recovery_codes_left }))
      onSession(session)
    } catch (error) {
      setCode('')
      codeError(error, onRestart)
    }
  }
  return <form onSubmit={(event) => { event.preventDefault(); void submit() }}>
    <VStack gap={4}>
      <VStack gap={1}>
        <Heading level={1}>{t('con.tf.verifyTitle')}</Heading>
        <Text type="supporting">{useRecovery
          ? t('con.tf.recoveryHint')
          : t('con.tf.appHint')}</Text>
      </VStack>
      {useRecovery
        ? <TextInput key="recovery" label={t('con.tf.recoveryCode')} value={code} onChange={setCode} placeholder="xxxxx-xxxxx" autoComplete="off" isRequired hasAutoFocus />
        : <TextInput key="app" label={t('con.tf.code')} value={code} onChange={setCode} placeholder="000000" autoComplete="one-time-code" htmlName="one-time-code" isRequired hasAutoFocus />}
      <Button label={t('con.tf.verify')} variant="primary" type="submit" isDisabled={!ready || verify.isPending} />
      <HStack gap={2} hAlign="between">
        <Button label={t('con.tf.back')} variant="ghost" size="sm" onClick={onRestart} />
        <Button label={useRecovery ? t('con.tf.useApp') : t('con.tf.useRecovery')} variant="ghost" size="sm" icon={<KeyRound size={14} />}
          onClick={() => { setCode(''); setUseRecovery(!useRecovery) }} />
      </HStack>
    </VStack>
  </form>
}
