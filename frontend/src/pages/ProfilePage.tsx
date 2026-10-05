import { LANGUAGE_NAMES } from '../components/LanguageSwitcher'
import { LANGUAGES } from '../locales/languages'
import i18n from '../i18n'
import { useTranslation } from 'react-i18next'
import { useEffect, useMemo, useState } from "react";
import {
  Bell,
  BriefcaseBusiness,
  Building2,
  CalendarDays,
  Check,
  Compass,
  ImageUp,
  KeyRound,
  Languages,
  Lock,
  Phone,
  Save,
  Send,
  ShieldCheck,
  UserRound,
  Volume2,
} from "lucide-react";
import { Avatar } from "@astryxdesign/core/Avatar";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { DateInput } from "@astryxdesign/core/DateInput";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Divider } from "@astryxdesign/core/Divider";
import { FileInput } from "@astryxdesign/core/FileInput";
import { Grid } from "@astryxdesign/core/Grid";
import { Heading } from "@astryxdesign/core/Heading";
import { HStack } from "@astryxdesign/core/HStack";
import { Icon } from "@astryxdesign/core/Icon";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { SelectableCard } from "@astryxdesign/core/SelectableCard";
import { Selector } from "@astryxdesign/core/Selector";
import { StackItem } from "@astryxdesign/core/Stack";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Switch } from "@astryxdesign/core/Switch";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Token } from "@astryxdesign/core/Token";
import { VStack } from "@astryxdesign/core/VStack";
import {
  useChangeProfilePassword,
  useChatNotificationPreferences,
  useHRDepartments,
  useProfile,
  useTelegramProfileLink,
  useUpdateProfile,
  useUpdateChatNotificationPreferences,
  useUploadAvatar,
  type UserProfile,
} from "../api/enterprise";
import { notificationService, type NotificationPermissionState } from "../platform/notifications";
import { NotificationPreferencesCard } from "../components/NotificationPreferencesCard";
import { AutoWorktimeCard } from "../components/AutoWorktimeCard";
import { BiometricLockCard } from "../components/BiometricLock";
import { isNativePlatform, resolvePublicAssetUrl } from "../platform/runtime";
import { desktopChatPermission, previewChatSound, requestDesktopChatPermission } from "../platform/chat-notifications";

const MEMOJI_OPTIONS = Array.from(
  { length: 10 },
  (_, index) => `/emojis/memoji-${String(index + 1).padStart(2, "0")}.png`,
);

// Each language under its own name, in the order the profile has always listed them.
const LOCALE_OPTIONS = (['mn', 'en', 'ru'] as const).map((value) => ({ value, label: LANGUAGE_NAMES[value].full }));

const ROLE_KEYS = ["member", "manager", "team_lead", "hr", "contractor", "client_auditor", "legal_counsel", "admin"];
const roleLabel = (role: string) => (ROLE_KEYS.includes(role) ? i18n.t(`profile.role.${role}`) : role);

const EMPLOYMENT_TYPE_KEYS = ["full_time", "part_time", "contract", "intern"];
const employmentTypeLabel = (type: string) => (EMPLOYMENT_TYPE_KEYS.includes(type) ? i18n.t(`profile.employmentType.${type}`) : "");

type ProfileForm = {
  username: string;
  avatar_url: string;
  locale: string;
  phone_number: string;
  birthday: string;
  work_direction: string;
  department_id: string;
  username_password: string;
};

function toForm(profile?: UserProfile): ProfileForm {
  return {
    username: profile?.username ?? "",
    avatar_url: profile?.avatar_url?.startsWith("/") ? profile.avatar_url : "",
    locale: profile?.locale ?? "mn",
    phone_number: profile?.phone_number ?? "",
    birthday: profile?.birthday ?? "",
    work_direction: profile?.work_direction ?? "",
    department_id: profile?.department_id ? String(profile.department_id) : "",
    username_password: "",
  };
}

const sameForm = (a: ProfileForm, b: ProfileForm) =>
  (Object.keys(a) as (keyof ProfileForm)[]).every((key) => a[key] === b[key]);

function tenureLabel(startDate: string | null) {
  if (!startDate) return null;
  const start = new Date(`${startDate}T00:00:00`);
  const now = new Date();
  let months = (now.getFullYear() - start.getFullYear()) * 12 + now.getMonth() - start.getMonth();
  if (now.getDate() < start.getDate()) months -= 1;
  if (months < 0) return null;
  const years = Math.floor(months / 12);
  const rest = months % 12;
  if (!years && !rest) return i18n.t('profile.tenure.thisMonth');
  return [years ? i18n.t('profile.tenure.years', { n: years }) : "", rest ? i18n.t('profile.tenure.months', { n: rest }) : ""].filter(Boolean).join(" ");
}

function formatDate(value: string | null) {
  return value ? value.replaceAll("-", ".") : "—";
}

function SectionHeader({ icon, title, description, end }: { icon: React.ComponentType<React.SVGProps<SVGSVGElement>>; title: string; description?: string; end?: React.ReactNode }) {
  return (
    <HStack gap={3} vAlign="center">
      <Icon icon={icon} color="accent" size="md" />
      <StackItem size="fill">
        <VStack gap={0.5}>
          <Heading level={3}>{title}</Heading>
          {description && <Text type="supporting">{description}</Text>}
        </VStack>
      </StackItem>
      {end}
    </HStack>
  );
}

export function ProfilePage() {
  const { t } = useTranslation()
  const profile = useProfile();
  const departments = useHRDepartments();
  const update = useUpdateProfile();
  const changePassword = useChangeProfilePassword();
  const telegramLink = useTelegramProfileLink();
  const uploadAvatar = useUploadAvatar();
  const chatNotifications = useChatNotificationPreferences(!isNativePlatform());
  const updateChatNotifications = useUpdateChatNotificationPreferences();

  const baseline = useMemo(() => toForm(profile.data), [profile.data]);
  // Edits live in a draft so a background refetch never wipes unsaved input.
  const [draft, setDraft] = useState<ProfileForm | null>(null);
  const form = draft ?? baseline;
  const dirty = draft !== null && !sameForm(draft, baseline);
  const edit = (patch: Partial<ProfileForm>) => setDraft({ ...form, ...patch });

  const [passwordOpen, setPasswordOpen] = useState(false);
  const [passwords, setPasswords] = useState({ current: "", next: "" });
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [notificationPermission, setNotificationPermission] = useState<NotificationPermissionState>("unsupported");
  const [notificationPending, setNotificationPending] = useState(false);
  const [desktopPermission, setDesktopPermission] = useState(() => desktopChatPermission());

  useEffect(() => {
    if (!isNativePlatform()) return;
    void notificationService.getPermissionState().then(setNotificationPermission);
    return notificationService.subscribeToEvents((event) => {
      if (event.type === "permission") setNotificationPermission(event.state);
    });
  }, []);

  const data = profile.data;
  const needsPasswordSetup = data?.requires_password_setup ?? false;
  // Telegram sign-ins (and accounts without an own password yet) change the
  // username and password without typing the current password.
  const needsCurrentPassword = data?.credentials_require_current_password ?? !needsPasswordSetup;
  const usernameChanged = !!data && form.username !== data.username;
  const departmentLocked = data?.department_locked ?? false;

  const departmentOptions = useMemo(() => {
    const rows = (departments.data ?? []).filter((row) => row.is_active || String(row.id) === form.department_id);
    return rows.map((row) => ({
      value: String(row.id),
      label: row.name,
      description: row.description || t('profile.employeeCount', { n: row.employee_count }),
    }));
  }, [departments.data, form.department_id]);

  const completion = useMemo(() => {
    const checks = [
      { label: t('profile.field.photo'), done: !!form.avatar_url },
      { label: t('profile.field.phone'), done: !!form.phone_number.trim() },
      { label: t('profile.field.birthday'), done: !!form.birthday },
      { label: t('profile.field.department'), done: !!form.department_id },
      { label: t('profile.field.workDirection'), done: !!form.work_direction.trim() },
      { label: t('profile.telegram'), done: !!data?.telegram_connected },
      { label: t('profile.field.password'), done: !needsPasswordSetup },
    ];
    const done = checks.filter((item) => item.done).length;
    return { percent: Math.round((done / checks.length) * 100), missing: checks.filter((item) => !item.done) };
  }, [form, data?.telegram_connected, needsPasswordSetup]);

  const departmentName =
    departmentOptions.find((option) => option.value === form.department_id)?.label ?? data?.department_name ?? null;
  const subtitle = [data?.job_title, departmentName].filter(Boolean).join(" · ");
  const tenure = tenureLabel(data?.start_date ?? null);
  const avatarSrc = form.avatar_url ? resolvePublicAssetUrl(form.avatar_url) || undefined : undefined;

  const saveProfile = async () => {
    const payload: Parameters<typeof update.mutateAsync>[0] = {
      username: form.username,
      avatar_url: form.avatar_url || null,
      locale: form.locale,
      phone_number: form.phone_number.trim() || null,
      birthday: form.birthday || null,
      work_direction: form.work_direction.trim() || null,
      current_password: form.username_password || undefined,
    };
    if (form.department_id !== baseline.department_id)
      payload.department_id = form.department_id ? Number(form.department_id) : null;
    await update.mutateAsync(payload);
    setDraft(null);
    // The saved locale takes effect immediately instead of on the next sign-in.
    if ((LANGUAGES as readonly string[]).includes(form.locale) && i18n.language !== form.locale) await i18n.changeLanguage(form.locale);
  };

  const submitPassword = async (event: React.FormEvent) => {
    event.preventDefault();
    await changePassword.mutateAsync({ current_password: passwords.current || undefined, new_password: passwords.next });
    setPasswords({ current: "", next: "" });
    setPasswordOpen(false);
  };

  const linkTelegram = () => {
    const initData = (window as any).Telegram?.WebApp?.initData;
    if (initData) telegramLink.mutate(initData);
    else window.location.href = "/tg";
  };

  const chooseUpload = async (files: File | File[] | null) => {
    const file = Array.isArray(files) ? files[0] : files;
    setUploadFile(file ?? null);
    if (!file) return;
    try {
      const result = await uploadAvatar.mutateAsync(file);
      // The upload is already stored server-side; keep any other unsaved edits.
      if (draft) setDraft({ ...draft, avatar_url: result.avatar_url });
    } finally {
      setUploadFile(null);
    }
  };

  const requestNotifications = async () => {
    setNotificationPending(true);
    try {
      setNotificationPermission(await notificationService.requestPermissionAndRegister());
    } finally {
      setNotificationPending(false);
    }
  };

  const desktopEnabled = !!chatNotifications.data?.desktop_alerts_enabled && desktopPermission === "granted";
  const soundEnabled = chatNotifications.data?.sound_enabled ?? true;
  const toggleDesktopAlerts = async (next: boolean) => {
    if (!next) {
      await updateChatNotifications.mutateAsync({ desktop_alerts_enabled: false, sound_enabled: soundEnabled });
      return;
    }
    setNotificationPending(true);
    try {
      const permission = await requestDesktopChatPermission();
      setDesktopPermission(permission);
      if (permission === "granted") {
        await updateChatNotifications.mutateAsync({ desktop_alerts_enabled: true, sound_enabled: soundEnabled });
        if (soundEnabled) await previewChatSound();
      }
    } finally {
      setNotificationPending(false);
    }
  };

  return (
    <VStack gap={5}>
      {/* Identity hero */}
      <Card padding={6} elevation="low">
        <Grid columns={{ minWidth: 320, max: 2, repeat: "fit" }} gap={6} align="center">
          <HStack gap={5} vAlign="center" wrap="wrap">
            <Avatar src={avatarSrc} name={data?.name} size={96} tooltip={false} />
            <StackItem size="fill">
              <VStack gap={2}>
                <VStack gap={0.5}>
                  <Heading level={2}>{data?.name ?? "…"}</Heading>
                  <Text color="secondary">{subtitle || t('profile.noPosition')}</Text>
                </VStack>
                <HStack gap={2} wrap="wrap" vAlign="center">
                  {(data?.roles ?? []).map((role) => (
                    <Token key={role} size="sm" color="blue" label={roleLabel(role)} />
                  ))}
                  <Token
                    size="sm"
                    color={data?.telegram_connected ? "green" : "gray"}
                    icon={<Send size={12} />}
                    label={data?.telegram_connected ? `@${data.telegram_username || t('profile.telegram.linkedLower')}` : t('profile.telegram.notLinked')}
                  />
                  {tenure && <Token size="sm" color="purple" icon={<CalendarDays size={12} />} label={tenure} />}
                </HStack>
              </VStack>
            </StackItem>
          </HStack>
          <VStack gap={2}>
            <HStack gap={2} vAlign="center">
              <StackItem size="fill">
                <Text weight="semibold">{t('profile.completeness')}</Text>
              </StackItem>
              <Text weight="semibold" color={completion.percent === 100 ? "accent" : "secondary"} hasTabularNumbers>
                {completion.percent}%
              </Text>
            </HStack>
            <ProgressBar
              label={t('profile.completeness')}
              isLabelHidden
              value={completion.percent}
              variant={completion.percent === 100 ? "success" : "accent"}
            />
            {completion.missing.length ? (
              <HStack gap={1.5} wrap="wrap" vAlign="center">
                <Text type="supporting">{t('profile.missing')}</Text>
                {completion.missing.map((item) => (
                  <Token key={item.label} size="sm" label={item.label} />
                ))}
              </HStack>
            ) : (
              <Text type="supporting">{t('profile.complete')}</Text>
            )}
          </VStack>
        </Grid>
      </Card>

      {needsPasswordSetup && (
        <Banner
          status="warning"
          title={t('profile.password.notCreated')}
          description={t('profile.password.setupBanner', { username: data?.username ?? "" })}
          endContent={<Button label={t('profile.password.create')} size="sm" onClick={() => setPasswordOpen(true)} />}
          collapsible={false}
        />
      )}

      <Grid columns={{ minWidth: 360, max: 2, repeat: "fit" }} gap={5} align="start">
        {/* Primary column */}
        <VStack gap={5}>
          <Card padding={5}>
            <VStack gap={4}>
              <SectionHeader icon={UserRound} title={t('profile.personal')} description={t('profile.personalHint')} />
              <Grid columns={{ minWidth: 220, max: 2, repeat: "fit" }} gap={4}>
                <TextInput
                  label={t('profile.field.phone')}
                  startIcon={Phone}
                  placeholder={t('profile.phonePlaceholder')}
                  value={form.phone_number}
                  onChange={(value) => edit({ phone_number: value })}
                  autoComplete="tel"
                />
                <DateInput
                  label={t('profile.field.birthday')}
                  value={(form.birthday || undefined) as any}
                  onChange={(value) => edit({ birthday: value ?? "" })}
                  max={new Date().toISOString().slice(0, 10) as any}
                  format="system_date"
                  weekStartsOn="mon"
                  hasClear
                />
              </Grid>
            </VStack>
          </Card>

          <Card padding={5}>
            <VStack gap={4}>
              <SectionHeader
                icon={BriefcaseBusiness}
                title={t('profile.work')}
                description={t('profile.workHint')}
              />
              <Grid columns={{ minWidth: 220, max: 2, repeat: "fit" }} gap={4}>
                <Selector
                  label={t('profile.field.department')}
                  placeholder={departments.isLoading ? t('profile.loading') : t('profile.pickDepartment')}
                  options={departmentOptions}
                  value={form.department_id || undefined}
                  onChange={(value) => edit({ department_id: value ?? "" })}
                  hasSearch={departmentOptions.length > 7}
                  searchPlaceholder={t('profile.searchDepartment')}
                  emptyText={t('profile.noDepartments')}
                  isReadOnly={departmentLocked}
                  description={departmentLocked ? t('profile.assignedByHr') : undefined}
                />
                <TextInput
                  label={t('profile.field.workDirection')}
                  startIcon={Compass}
                  placeholder={t('profile.workDirectionPlaceholder')}
                  value={form.work_direction}
                  onChange={(value) => edit({ work_direction: value })}
                />
              </Grid>
              <Divider />
              <HStack gap={2} vAlign="center">
                <Icon icon={Lock} size="sm" color="secondary" />
                <Text type="supporting">{t('profile.hrReadOnly')}</Text>
              </HStack>
              <MetadataList columns={2}>
                <MetadataListItem label={t('profile.position')} icon={<Building2 size={14} />}>
                  <Text>{data?.job_title || "—"}</Text>
                </MetadataListItem>
                <MetadataListItem label={t('profile.manager')} icon={<UserRound size={14} />}>
                  {data?.manager_name ? (
                    <HStack gap={2} vAlign="center">
                      <Avatar
                        size="sm"
                        name={data.manager_name}
                        src={data.manager_avatar_url ? resolvePublicAssetUrl(data.manager_avatar_url) || undefined : undefined}
                      />
                      <Text>{data.manager_name}</Text>
                    </HStack>
                  ) : (
                    <Text>—</Text>
                  )}
                </MetadataListItem>
                <MetadataListItem label={t('profile.hired')} icon={<CalendarDays size={14} />}>
                  <Text>
                    {formatDate(data?.start_date ?? null)}
                    {tenure ? ` · ${tenure}` : ""}
                  </Text>
                </MetadataListItem>
                <MetadataListItem label={t('profile.employmentType')} icon={<BriefcaseBusiness size={14} />}>
                  <Text>{(data?.employment_type && employmentTypeLabel(data.employment_type)) || "—"}</Text>
                </MetadataListItem>
              </MetadataList>
            </VStack>
          </Card>

          <Card padding={5}>
            <VStack gap={4}>
              <SectionHeader icon={ImageUp} title={t('profile.avatar')} description={t('profile.avatarHint')} />
              <Grid columns={{ minWidth: 60, max: 5 }} gap={2}>
                {MEMOJI_OPTIONS.map((url, index) => (
                  <SelectableCard
                    key={url}
                    label={`Memoji ${index + 1}`}
                    isSelected={form.avatar_url === url}
                    onChange={() => edit({ avatar_url: url })}
                    padding={1}
                  >
                    <HStack hAlign="center">
                      <Avatar src={url} name={`Memoji ${index + 1}`} size="lg" tooltip={false} />
                    </HStack>
                  </SelectableCard>
                ))}
              </Grid>
              <FileInput
                label={t('profile.uploadAvatar')}
                isLabelHidden
                mode="dropzone"
                accept="image/png,image/jpeg,image/webp"
                maxSize={2 * 1024 * 1024}
                value={uploadFile}
                onChange={chooseUpload}
                isLoading={uploadAvatar.isPending}
                placeholder={t('profile.uploadHint')}
              />
            </VStack>
          </Card>
        </VStack>

        {/* Account column */}
        <VStack gap={5}>
          <Card padding={5}>
            <VStack gap={4}>
              <SectionHeader icon={ShieldCheck} title={t('profile.security')} />
              <TextInput
                label={t('profile.username')}
                value={form.username}
                onChange={(value) => edit({ username: value })}
                description={
                  data?.telegram_session
                    ? t('profile.usernameHintTelegram')
                    : needsPasswordSetup
                      ? t('profile.usernameHintSetup')
                      : undefined
                }
                autoComplete="username"
              />
              {usernameChanged && needsCurrentPassword && (
                <TextInput
                  type="password"
                  label={t('profile.currentPassword')}
                  description={t('profile.usernameConfirm')}
                  value={form.username_password}
                  onChange={(value) => edit({ username_password: value })}
                  autoComplete="current-password"
                />
              )}
              <HStack gap={3} vAlign="center">
                <Icon icon={KeyRound} color="secondary" />
                <StackItem size="fill">
                  <VStack gap={0.5}>
                    <Text weight="medium">{t('profile.field.password')}</Text>
                    <Text type="supporting">{needsPasswordSetup ? t('profile.password.none') : t('profile.password.set')}</Text>
                  </VStack>
                </StackItem>
                <Button
                  label={needsPasswordSetup ? t('profile.create') : t('profile.change')}
                  size="sm"
                  onClick={() => setPasswordOpen(true)}
                />
              </HStack>
              <Divider />
              <HStack gap={3} vAlign="center">
                <Icon icon={Send} color="secondary" />
                <StackItem size="fill">
                  <VStack gap={0.5}>
                    <HStack gap={1.5} vAlign="center">
                      <Text weight="medium">{t('profile.telegram')}</Text>
                      <StatusDot
                        variant={data?.telegram_connected ? "success" : "neutral"}
                        label={data?.telegram_connected ? t('profile.telegram.linked') : t('profile.telegram.unlinked')}
                      />
                    </HStack>
                    <Text type="supporting">
                      {data?.telegram_connected ? `@${data.telegram_username || t('profile.telegram.linkedLower')}` : t('profile.telegram.hint')}
                    </Text>
                  </VStack>
                </StackItem>
                <Button
                  label={data?.telegram_connected ? t('profile.telegram.relink') : t('profile.telegram.link')}
                  size="sm"
                  onClick={linkTelegram}
                  isLoading={telegramLink.isPending}
                />
              </HStack>
            </VStack>
          </Card>

          <Card padding={5}>
            <VStack gap={4}>
              <SectionHeader icon={Languages} title={t('profile.settings')} />
              <Selector
                label={t('profile.language')}
                options={LOCALE_OPTIONS}
                value={form.locale}
                onChange={(value) => value && edit({ locale: value })}
              />
            </VStack>
          </Card>

          <Card padding={5}>
            <VStack gap={4}>
              <SectionHeader icon={Bell} title={t('profile.notifications')} />
              {isNativePlatform() ? (
                <HStack gap={3} vAlign="center">
                  <StackItem size="fill">
                    <VStack gap={0.5}>
                      <Text weight="medium">{t('profile.push')}</Text>
                      <Text type="supporting">{t('profile.pushHint')}</Text>
                    </VStack>
                  </StackItem>
                  {notificationPermission === "granted" ? (
                    <Token size="sm" color="green" icon={<Check size={12} />} label={t('profile.active')} />
                  ) : (
                    <Button
                      size="sm"
                      label={notificationPermission === "denied" ? t('profile.allowInSettings') : t('profile.allow')}
                      onClick={requestNotifications}
                      isLoading={notificationPending}
                      isDisabled={notificationPermission === "denied"}
                    />
                  )}
                </HStack>
              ) : (
                <>
                  <Switch
                    label={t('profile.desktopNotif')}
                    description={
                      desktopPermission === "denied"
                        ? t('profile.desktopNotifDenied')
                        : t('profile.desktopNotifHint')
                    }
                    value={desktopEnabled}
                    onChange={(next) => void toggleDesktopAlerts(next)}
                    isLoading={notificationPending || updateChatNotifications.isPending}
                    isDisabled={desktopPermission === "denied"}
                    labelPosition="start"
                    labelSpacing="spread"
                    width="100%"
                  />
                  <HStack gap={2} vAlign="center">
                    <StackItem size="fill">
                      <Switch
                        label={t('profile.sound')}
                        value={soundEnabled}
                        onChange={(next) =>
                          updateChatNotifications.mutate({
                            desktop_alerts_enabled: chatNotifications.data?.desktop_alerts_enabled ?? false,
                            sound_enabled: next,
                          })
                        }
                        isDisabled={!desktopEnabled}
                        labelPosition="start"
                        labelSpacing="spread"
                        width="100%"
                      />
                    </StackItem>
                    <Button
                      label={t('profile.listen')}
                      size="sm"
                      variant="ghost"
                      icon={<Volume2 size={14} />}
                      isIconOnly
                      tooltip={t('profile.listenSound')}
                      onClick={() => void previewChatSound()}
                    />
                  </HStack>
                </>
              )}
            </VStack>
          </Card>

          <NotificationPreferencesCard />
          <AutoWorktimeCard />
          <BiometricLockCard />
        </VStack>
      </Grid>

      {dirty && (
        <Card padding={3} elevation="high" className="sticky bottom-4 z-20">
          <HStack gap={3} vAlign="center" wrap="wrap">
            <StatusDot variant="warning" label={t('profile.unsaved')} />
            <StackItem size="fill">
              <Text weight="medium">{t('profile.unsavedChanges')}</Text>
            </StackItem>
            <Button label={t('profile.revert')} variant="ghost" onClick={() => setDraft(null)} isDisabled={update.isPending} />
            <Button
              label={t('profile.save')}
              variant="primary"
              icon={<Save size={16} />}
              clickAction={saveProfile}
              isLoading={update.isPending}
              isDisabled={!form.username.trim() || (usernameChanged && needsCurrentPassword && !form.username_password)}
            />
          </HStack>
        </Card>
      )}

      <Dialog isOpen={passwordOpen} onOpenChange={setPasswordOpen} purpose="form" width={440}>
        <form onSubmit={submitPassword}>
          <VStack gap={4}>
            <DialogHeader
              title={needsPasswordSetup ? t('profile.password.create') : t('profile.password.change')}
              subtitle={
                needsPasswordSetup
                  ? t('profile.password.setupFor', { username: data?.username ?? "" })
                  : needsCurrentPassword
                    ? t('profile.password.confirmCurrent')
                    : t('profile.password.noCurrent')
              }
              onOpenChange={setPasswordOpen}
            />
            <VStack gap={4} paddingInline={4}>
              {needsCurrentPassword && (
                <TextInput
                  type="password"
                  label={t('profile.currentPassword')}
                  value={passwords.current}
                  onChange={(value) => setPasswords((current) => ({ ...current, current: value }))}
                  autoComplete="current-password"
                  hasAutoFocus
                />
              )}
              <TextInput
                type="password"
                label={t('profile.password.new')}
                description={t('profile.password.minHint')}
                value={passwords.next}
                onChange={(value) => setPasswords((current) => ({ ...current, next: value }))}
                autoComplete="new-password"
                hasAutoFocus={!needsCurrentPassword}
                status={
                  passwords.next && passwords.next.length < 10
                    ? { type: "warning", message: t('profile.password.charsLeft', { n: 10 - passwords.next.length }) }
                    : undefined
                }
              />
            </VStack>
            <HStack gap={2} hAlign="end" padding={4}>
              <Button label={t('profile.cancel')} variant="ghost" onClick={() => setPasswordOpen(false)} />
              <Button
                type="submit"
                label={t('profile.savePassword')}
                variant="primary"
                icon={<Save size={16} />}
                isLoading={changePassword.isPending}
                isDisabled={passwords.next.length < 10 || (needsCurrentPassword && !passwords.current)}
              />
            </HStack>
          </VStack>
        </form>
      </Dialog>
    </VStack>
  );
}
