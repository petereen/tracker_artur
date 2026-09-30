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
import { isNativePlatform, resolvePublicAssetUrl } from "../platform/runtime";
import { desktopChatPermission, previewChatSound, requestDesktopChatPermission } from "../platform/chat-notifications";

const MEMOJI_OPTIONS = Array.from(
  { length: 10 },
  (_, index) => `/emojis/memoji-${String(index + 1).padStart(2, "0")}.png`,
);

const LOCALE_OPTIONS = [
  { value: "mn", label: "Монгол" },
  { value: "en", label: "English" },
  { value: "ru", label: "Русский" },
];

const ROLE_LABELS: Record<string, string> = {
  member: "Ажилтан",
  manager: "Удирдлага",
  team_lead: "Багийн ахлагч",
  hr: "HR",
  contractor: "Гэрээт",
  client_auditor: "Аудитор",
  legal_counsel: "Хуульч",
  admin: "Админ",
};

const EMPLOYMENT_TYPE_LABELS: Record<string, string> = {
  full_time: "Бүтэн цаг",
  part_time: "Цагийн",
  contract: "Гэрээт",
  intern: "Дадлагажигч",
};

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
  if (!years && !rest) return "Энэ сард эхэлсэн";
  return [years ? `${years} жил` : "", rest ? `${rest} сар` : ""].filter(Boolean).join(" ");
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
      description: row.description || `${row.employee_count} ажилтан`,
    }));
  }, [departments.data, form.department_id]);

  const completion = useMemo(() => {
    const checks = [
      { label: "Зураг", done: !!form.avatar_url },
      { label: "Утас", done: !!form.phone_number.trim() },
      { label: "Төрсөн өдөр", done: !!form.birthday },
      { label: "Алба", done: !!form.department_id },
      { label: "Ажлын чиглэл", done: !!form.work_direction.trim() },
      { label: "Telegram", done: !!data?.telegram_connected },
      { label: "Нууц үг", done: !needsPasswordSetup },
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
                  <Text color="secondary">{subtitle || "Албан тушаал, алба оноогдоогүй"}</Text>
                </VStack>
                <HStack gap={2} wrap="wrap" vAlign="center">
                  {(data?.roles ?? []).map((role) => (
                    <Token key={role} size="sm" color="blue" label={ROLE_LABELS[role] ?? role} />
                  ))}
                  <Token
                    size="sm"
                    color={data?.telegram_connected ? "green" : "gray"}
                    icon={<Send size={12} />}
                    label={data?.telegram_connected ? `@${data.telegram_username || "холбогдсон"}` : "Telegram холбоогүй"}
                  />
                  {tenure && <Token size="sm" color="purple" icon={<CalendarDays size={12} />} label={tenure} />}
                </HStack>
              </VStack>
            </StackItem>
          </HStack>
          <VStack gap={2}>
            <HStack gap={2} vAlign="center">
              <StackItem size="fill">
                <Text weight="semibold">Профайлын бүрдэл</Text>
              </StackItem>
              <Text weight="semibold" color={completion.percent === 100 ? "accent" : "secondary"} hasTabularNumbers>
                {completion.percent}%
              </Text>
            </HStack>
            <ProgressBar
              label="Профайлын бүрдэл"
              isLabelHidden
              value={completion.percent}
              variant={completion.percent === 100 ? "success" : "accent"}
            />
            {completion.missing.length ? (
              <HStack gap={1.5} wrap="wrap" vAlign="center">
                <Text type="supporting">Дутуу:</Text>
                {completion.missing.map((item) => (
                  <Token key={item.label} size="sm" label={item.label} />
                ))}
              </HStack>
            ) : (
              <Text type="supporting">Бүх мэдээлэл бүрэн. Хамт олон таныг хялбар олох боломжтой.</Text>
            )}
          </VStack>
        </Grid>
      </Card>

      {needsPasswordSetup && (
        <Banner
          status="warning"
          title="Нууц үг үүсгээгүй байна"
          description={`Telegram-аар нэвтэрсэн тул вэбээр нэвтрэх нэр, нууц үгээ тохируулна уу. Одоогийн нэвтрэх нэр: ${data?.username ?? ""}`}
          endContent={<Button label="Нууц үг үүсгэх" size="sm" onClick={() => setPasswordOpen(true)} />}
          collapsible={false}
        />
      )}

      <Grid columns={{ minWidth: 360, max: 2, repeat: "fit" }} gap={5} align="start">
        {/* Primary column */}
        <VStack gap={5}>
          <Card padding={5}>
            <VStack gap={4}>
              <SectionHeader icon={UserRound} title="Хувийн мэдээлэл" description="Байгууллагын ажилтнуудад харагдана." />
              <Grid columns={{ minWidth: 220, max: 2, repeat: "fit" }} gap={4}>
                <TextInput
                  label="Утас"
                  startIcon={Phone}
                  placeholder="99xxxxxx"
                  value={form.phone_number}
                  onChange={(value) => edit({ phone_number: value })}
                  autoComplete="tel"
                />
                <DateInput
                  label="Төрсөн өдөр"
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
                title="Ажлын мэдээлэл"
                description="Алба HR-ын бүртгэлээс сонгогдоно."
              />
              <Grid columns={{ minWidth: 220, max: 2, repeat: "fit" }} gap={4}>
                <Selector
                  label="Алба"
                  placeholder={departments.isLoading ? "Ачаалж байна…" : "Албаа сонгоно уу"}
                  options={departmentOptions}
                  value={form.department_id || undefined}
                  onChange={(value) => edit({ department_id: value ?? "" })}
                  hasSearch={departmentOptions.length > 7}
                  searchPlaceholder="Алба хайх…"
                  emptyText="HR алба бүртгээгүй байна"
                  isReadOnly={departmentLocked}
                  description={departmentLocked ? "HR оноосон. Өөрчлөх бол HR-т хандана уу." : undefined}
                />
                <TextInput
                  label="Ажлын чиглэл"
                  startIcon={Compass}
                  placeholder="Жишээ: Систем хөгжүүлэлт"
                  value={form.work_direction}
                  onChange={(value) => edit({ work_direction: value })}
                />
              </Grid>
              <Divider />
              <HStack gap={2} vAlign="center">
                <Icon icon={Lock} size="sm" color="secondary" />
                <Text type="supporting">HR-ын бүртгэл — зөвхөн унших</Text>
              </HStack>
              <MetadataList columns={2}>
                <MetadataListItem label="Албан тушаал" icon={<Building2 size={14} />}>
                  <Text>{data?.job_title || "—"}</Text>
                </MetadataListItem>
                <MetadataListItem label="Шууд удирдлага" icon={<UserRound size={14} />}>
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
                <MetadataListItem label="Ажилд орсон" icon={<CalendarDays size={14} />}>
                  <Text>
                    {formatDate(data?.start_date ?? null)}
                    {tenure ? ` · ${tenure}` : ""}
                  </Text>
                </MetadataListItem>
                <MetadataListItem label="Ажлын төрөл" icon={<BriefcaseBusiness size={14} />}>
                  <Text>{(data?.employment_type && EMPLOYMENT_TYPE_LABELS[data.employment_type]) || "—"}</Text>
                </MetadataListItem>
              </MetadataList>
            </VStack>
          </Card>

          <Card padding={5}>
            <VStack gap={4}>
              <SectionHeader icon={ImageUp} title="Профайл зураг" description="Memoji сонгох эсвэл өөрийн зургаа оруулна." />
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
                label="Өөрийн зураг оруулах"
                isLabelHidden
                mode="dropzone"
                accept="image/png,image/jpeg,image/webp"
                maxSize={2 * 1024 * 1024}
                value={uploadFile}
                onChange={chooseUpload}
                isLoading={uploadAvatar.isPending}
                placeholder="Зураг чирж оруулах эсвэл сонгох · PNG, JPEG, WebP · 256×256, 2 MB"
              />
            </VStack>
          </Card>
        </VStack>

        {/* Account column */}
        <VStack gap={5}>
          <Card padding={5}>
            <VStack gap={4}>
              <SectionHeader icon={ShieldCheck} title="Нэвтрэлт ба аюулгүй байдал" />
              <TextInput
                label="Нэвтрэх нэр"
                value={form.username}
                onChange={(value) => edit({ username: value })}
                description={
                  data?.telegram_session
                    ? "Telegram-аар нэвтэрсэн тул нэвтрэх нэр, нууц үгээ одоогийн нууц үггүйгээр сольж болно."
                    : needsPasswordSetup
                      ? "Нэвтрэх нэр ба нууц үгээ тохируулж, вебээр шууд нэвтэрнэ."
                      : undefined
                }
                autoComplete="username"
              />
              {usernameChanged && needsCurrentPassword && (
                <TextInput
                  type="password"
                  label="Одоогийн нууц үг"
                  description="Нэвтрэх нэр солихыг баталгаажуулна."
                  value={form.username_password}
                  onChange={(value) => edit({ username_password: value })}
                  autoComplete="current-password"
                />
              )}
              <HStack gap={3} vAlign="center">
                <Icon icon={KeyRound} color="secondary" />
                <StackItem size="fill">
                  <VStack gap={0.5}>
                    <Text weight="medium">Нууц үг</Text>
                    <Text type="supporting">{needsPasswordSetup ? "Үүсгээгүй" : "Тохируулсан"}</Text>
                  </VStack>
                </StackItem>
                <Button
                  label={needsPasswordSetup ? "Үүсгэх" : "Солих"}
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
                      <Text weight="medium">Telegram</Text>
                      <StatusDot
                        variant={data?.telegram_connected ? "success" : "neutral"}
                        label={data?.telegram_connected ? "Холбогдсон" : "Холбоогүй"}
                      />
                    </HStack>
                    <Text type="supporting">
                      {data?.telegram_connected ? `@${data.telegram_username || "холбогдсон"}` : "Бот, мэдэгдэл хүлээн авахын тулд холбоно."}
                    </Text>
                  </VStack>
                </StackItem>
                <Button
                  label={data?.telegram_connected ? "Дахин холбох" : "Холбох"}
                  size="sm"
                  onClick={linkTelegram}
                  isLoading={telegramLink.isPending}
                />
              </HStack>
            </VStack>
          </Card>

          <Card padding={5}>
            <VStack gap={4}>
              <SectionHeader icon={Languages} title="Тохиргоо" />
              <Selector
                label="Хэл"
                options={LOCALE_OPTIONS}
                value={form.locale}
                onChange={(value) => value && edit({ locale: value })}
              />
            </VStack>
          </Card>

          <Card padding={5}>
            <VStack gap={4}>
              <SectionHeader icon={Bell} title="Мэдэгдэл" />
              {isNativePlatform() ? (
                <HStack gap={3} vAlign="center">
                  <StackItem size="fill">
                    <VStack gap={0.5}>
                      <Text weight="medium">Push мэдэгдэл</Text>
                      <Text type="supporting">Төхөөрөмж дээрх ажлын мэдэгдлийг удирдана.</Text>
                    </VStack>
                  </StackItem>
                  {notificationPermission === "granted" ? (
                    <Token size="sm" color="green" icon={<Check size={12} />} label="Идэвхтэй" />
                  ) : (
                    <Button
                      size="sm"
                      label={notificationPermission === "denied" ? "Тохиргооноос зөвшөөрнө үү" : "Зөвшөөрөх"}
                      onClick={requestNotifications}
                      isLoading={notificationPending}
                      isDisabled={notificationPermission === "denied"}
                    />
                  )}
                </HStack>
              ) : (
                <>
                  <Switch
                    label="Чатын desktop мэдэгдэл"
                    description={
                      desktopPermission === "denied"
                        ? "Browser тохиргооноос мэдэгдлийг зөвшөөрнө үү."
                        : "Апп нуугдсан эсвэл minimize үед мэдэгдэл харуулна."
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
                        label="Мэдэгдлийн дуу"
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
                      label="Сонсох"
                      size="sm"
                      variant="ghost"
                      icon={<Volume2 size={14} />}
                      isIconOnly
                      tooltip="Дууг сонсох"
                      onClick={() => void previewChatSound()}
                    />
                  </HStack>
                </>
              )}
            </VStack>
          </Card>
        </VStack>
      </Grid>

      {dirty && (
        <Card padding={3} elevation="high" className="sticky bottom-4 z-20">
          <HStack gap={3} vAlign="center" wrap="wrap">
            <StatusDot variant="warning" label="Хадгалаагүй" />
            <StackItem size="fill">
              <Text weight="medium">Хадгалаагүй өөрчлөлт байна</Text>
            </StackItem>
            <Button label="Буцаах" variant="ghost" onClick={() => setDraft(null)} isDisabled={update.isPending} />
            <Button
              label="Профайл хадгалах"
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
              title={needsPasswordSetup ? "Нууц үг үүсгэх" : "Нууц үг солих"}
              subtitle={
                needsPasswordSetup
                  ? `«${data?.username ?? ""}» нэвтрэх нэрээр нууц үг үүсгэнэ.`
                  : needsCurrentPassword
                    ? "Аюулгүй байдлын үүднээс одоогийн нууц үгээ оруулна."
                    : "Telegram-аар баталгаажсан тул одоогийн нууц үг шаардахгүй."
              }
              onOpenChange={setPasswordOpen}
            />
            <VStack gap={4} paddingInline={4}>
              {needsCurrentPassword && (
                <TextInput
                  type="password"
                  label="Одоогийн нууц үг"
                  value={passwords.current}
                  onChange={(value) => setPasswords((current) => ({ ...current, current: value }))}
                  autoComplete="current-password"
                  hasAutoFocus
                />
              )}
              <TextInput
                type="password"
                label="Шинэ нууц үг"
                description="Хамгийн багадаа 10 тэмдэгт."
                value={passwords.next}
                onChange={(value) => setPasswords((current) => ({ ...current, next: value }))}
                autoComplete="new-password"
                hasAutoFocus={!needsCurrentPassword}
                status={
                  passwords.next && passwords.next.length < 10
                    ? { type: "warning", message: `${10 - passwords.next.length} тэмдэгт дутуу` }
                    : undefined
                }
              />
            </VStack>
            <HStack gap={2} hAlign="end" padding={4}>
              <Button label="Цуцлах" variant="ghost" onClick={() => setPasswordOpen(false)} />
              <Button
                type="submit"
                label="Хадгалах"
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
