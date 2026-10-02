import { type ReactNode, useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { QRCodeSVG } from 'qrcode.react'
import { Copy, Download, KeyRound, LogOut, ShieldCheck } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { CheckboxInput } from '@astryxdesign/core/CheckboxInput'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { Grid } from '@astryxdesign/core/Grid'
import { HStack } from '@astryxdesign/core/HStack'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import { useEnterpriseLogout } from '../api/enterprise'
import { tenancyErrorMessage, useTenantBranding } from '../api/tenancy'
import { twoFactorErrorCode, useTwoFactorCode, useTwoFactorEnrolment } from '../api/twoFactor'
import i18n from '../i18n'
import { DialogScrollBody } from './DialogScrollBody'

const isAppCode = (value: string) => /^\d{6}$/.test(value.replace(/\s/g, ''))

function codeError(error: unknown) {
  const status = (error as { response?: { status?: number } })?.response?.status
  if (status === 423) toast.error(i18n.t('tfa.locked'))
  else if (twoFactorErrorCode(error) === 'invalid_code') toast.error(i18n.t('tfa.invalidCode'))
  else toast.error(tenancyErrorMessage(error, i18n.t('tfa.verifyFailed')))
}

function LogoutButton() {
  const { t } = useTranslation()
  const logout = useEnterpriseLogout()
  return <Button label={t('action.logout')} variant="ghost" icon={<LogOut size={14} />} onClick={() => logout.mutate()} isDisabled={logout.isPending} />
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

function RecoveryCodes({ codes, account, issuer, onContinue }: { codes: string[]; account: string; issuer: string; onContinue: () => void }) {
  const { t } = useTranslation()
  const [saved, setSaved] = useState(false)
  const copy = async () => {
    try { await navigator.clipboard.writeText(codes.join('\n')); toast.success(t('tfa.copied')) } catch { toast.error(t('tfa.copyFailed')) }
  }
  const download = () => {
    const text = `${t('tfa.fileHeader', { issuer, account })}\n${t('tfa.fileNote')}\n\n${codes.join('\n')}\n`
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'oyuns-recovery-codes.txt'
    link.click()
    URL.revokeObjectURL(url)
  }
  return <>
    <DialogHeader title={t('tfa.saveCodes')} />
    <DialogScrollBody label={t('tfa.saveCodes')} actions={<Button label={t('tfa.continue')} variant="primary" isDisabled={!saved} onClick={onContinue} />}>
      <Text type="supporting">{t('tfa.enabled')}</Text>
      <Banner status="warning" title={t('tfa.noRepeat')} description={t('tfa.keepSafe')} collapsible={false} />
      <Grid columns={2} gap={2}>
        {codes.map((code) => <Text key={code} type="code">{code}</Text>)}
      </Grid>
      <HStack gap={2}>
        <Button label={t('tfa.copy')} variant="secondary" size="sm" icon={<Copy size={14} />} onClick={() => { void copy() }} />
        <Button label={t('tfa.download')} variant="secondary" size="sm" icon={<Download size={14} />} onClick={download} />
      </HStack>
      <CheckboxInput label={t('tfa.saved')} value={saved} onChange={setSaved} />
    </DialogScrollBody>
  </>
}

/** First time: connect an authenticator app (QR + first code), then save the recovery codes. */
function TwoFactorSetup({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const enrolment = useTwoFactorEnrolment()
  const enable = useTwoFactorCode('enable')
  const [code, setCode] = useState('')
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null)
  const data = enrolment.data

  // The session is already verified here; the gate stays up until the codes are saved.
  if (recoveryCodes && data) return <RecoveryCodes codes={recoveryCodes} account={data.account} issuer={data.issuer} onContinue={onDone} />

  const submit = async () => {
    try {
      setRecoveryCodes((await enable.mutateAsync(code.replace(/\s/g, ''))).recovery_codes ?? [])
    } catch (error) {
      setCode('')
      codeError(error)
    }
  }
  const copySecret = async () => {
    try { await navigator.clipboard.writeText(data?.secret ?? ''); toast.success(t('tfa.keyCopied')) } catch { toast.error(t('tfa.copyFailed')) }
  }
  return <form onSubmit={(event) => { event.preventDefault(); void submit() }} style={{ display: 'contents' }}>
    <DialogHeader title={t('tfa.setupTitle')} subtitle={t('tfa.setupSubtitle')} />
    <DialogScrollBody label={t('tfa.setupTitle')} actions={<>
      <LogoutButton />
      <Button label={t('tfa.enable')} variant="primary" type="submit" icon={<ShieldCheck size={14} />} isDisabled={!data || !isAppCode(code) || enable.isPending} />
    </>}>
      <Text type="supporting">{t('tfa.setupIntro')}</Text>
      {enrolment.isError
        ? <Banner status="error" title={t('tfa.setupFailed')} description={tenancyErrorMessage(enrolment.error, t('common.retry'))} collapsible={false} />
        : <VStack gap={4}>
          <SetupStep index={1} title={t('tfa.step1')}>
            <Text type="supporting">{t('tfa.step1Text')}</Text>
          </SetupStep>
          <SetupStep index={2} title={t('tfa.step2')}>
            <Text type="supporting">{t('tfa.step2Text')}</Text>
            {data
              // White quiet zone: the code has to stay scannable in the dark theme.
              ? <div style={{ background: '#fff', padding: 12, borderRadius: 8, width: 'fit-content', lineHeight: 0 }}>
                <QRCodeSVG value={data.otpauth_uri} size={176} level="M" title={t('tfa.qrTitle')} />
              </div>
              : <Skeleton width={200} height={200} />}
            <Text type="supporting">{t('tfa.manual', { account: data?.account ?? '…' })}</Text>
            <HStack gap={2} vAlign="center">
              <Text type="code">{data ? data.secret.replace(/(.{4})/g, '$1 ').trim() : '…'}</Text>
              <Button label={t('tfa.copyKey')} variant="ghost" size="sm" icon={<Copy size={14} />} isDisabled={!data} onClick={() => { void copySecret() }} />
            </HStack>
          </SetupStep>
          <SetupStep index={3} title={t('tfa.step3')}>
            <TextInput label={t('tfa.code')} value={code} onChange={setCode} placeholder="000000" autoComplete="one-time-code" htmlName="one-time-code" isRequired />
          </SetupStep>
        </VStack>}
    </DialogScrollBody>
  </form>
}

/** Every later sign-in: a code from the app, or a one-time recovery code. */
function TwoFactorVerify({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const branding = useTenantBranding()
  const verify = useTwoFactorCode('verify')
  const [code, setCode] = useState('')
  const [useRecovery, setUseRecovery] = useState(false)
  const ready = useRecovery ? code.trim().length >= 10 : isAppCode(code)
  const submit = async () => {
    try {
      const session = await verify.mutateAsync(code.trim())
      if (useRecovery && typeof session.recovery_codes_left === 'number') toast(t('tfa.recoveryUsed', { n: session.recovery_codes_left }))
      onDone()
    } catch (error) {
      setCode('')
      codeError(error)
    }
  }
  return <form onSubmit={(event) => { event.preventDefault(); void submit() }} style={{ display: 'contents' }}>
    <DialogHeader title={t('tfa.verifyTitle')} subtitle={t('tfa.verifySubtitle')} />
    <DialogScrollBody label={t('tfa.verifyTitle')} actions={<>
      <LogoutButton />
      <Button label={t('tfa.verify')} variant="primary" type="submit" isDisabled={!ready || verify.isPending} />
    </>}>
      <Text type="supporting">{useRecovery ? t('tfa.recoveryHint') : t('tfa.appHint', { issuer: branding.data?.name ?? 'OYUNS ERP' })}</Text>
      {useRecovery
        ? <TextInput key="recovery" label={t('tfa.recoveryCode')} value={code} onChange={setCode} placeholder="xxxxx-xxxxx" autoComplete="off" isRequired hasAutoFocus />
        : <TextInput key="app" label={t('tfa.code')} value={code} onChange={setCode} placeholder="000000" autoComplete="one-time-code" htmlName="one-time-code" isRequired hasAutoFocus />}
      <HStack>
        <Button label={useRecovery ? t('tfa.useApp') : t('tfa.useRecovery')} variant="ghost" size="sm" icon={<KeyRound size={14} />}
          onClick={() => { setCode(''); setUseRecovery(!useRecovery) }} />
      </HStack>
      {useRecovery && <Text type="supporting">{t('tfa.lostAccess')}</Text>}
    </DialogScrollBody>
  </form>
}

/**
 * Blocking pop-up for a session that owes the tenant's second factor: the
 * workspace is not rendered behind it (the API refuses every other request),
 * and the only ways out are finishing the step or signing out.
 */
export function TwoFactorGate({ enrolled, onDone }: { enrolled: boolean; onDone: () => void }) {
  // Fixed at mount: enrolling flips `enrolled`, but the recovery codes must stay on screen.
  const [mode] = useState<'setup' | 'verify'>(enrolled ? 'verify' : 'setup')
  return <Dialog isOpen onOpenChange={() => undefined} purpose="required" width={mode === 'setup' ? 520 : 420} maxHeight="92dvh">
    {mode === 'setup' ? <TwoFactorSetup onDone={onDone} /> : <TwoFactorVerify onDone={onDone} />}
  </Dialog>
}
