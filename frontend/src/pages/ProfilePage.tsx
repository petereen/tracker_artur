import { useEffect, useState } from "react";
import { Bell, ImageUp, KeyRound, Save, UserRound, X } from "lucide-react";
import {
  useChangeProfilePassword,
  useChatNotificationPreferences,
  useProfile,
  useTelegramProfileLink,
  useUpdateProfile,
  useUpdateChatNotificationPreferences,
  useUploadAvatar,
} from "../api/enterprise";
import { DropdownSelect } from "../components/DropdownSelect";
import { notificationService, type NotificationPermissionState } from "../platform/notifications";
import { isNativePlatform, resolvePublicAssetUrl } from "../platform/runtime";
import { desktopChatPermission, previewChatSound, requestDesktopChatPermission } from "../platform/chat-notifications";

const MEMOJI_OPTIONS = Array.from(
  { length: 10 },
  (_, index) => `/emojis/memoji-${String(index + 1).padStart(2, "0")}.png`,
);

export function ProfilePage() {
  const profile = useProfile();
  const update = useUpdateProfile();
  const changePassword = useChangeProfilePassword();
  const telegramLink = useTelegramProfileLink();
  const uploadAvatar = useUploadAvatar();
  const chatNotifications = useChatNotificationPreferences(!isNativePlatform());
  const updateChatNotifications = useUpdateChatNotificationPreferences();
  const [form, setForm] = useState({
    username: "",
    avatar_url: "",
    locale: "mn",
    phone_number: "",
    birthday: "",
    work_direction: "",
    work_branch: "",
    username_password: "",
    current_password: "",
    new_password: "",
  });
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [notificationPermission, setNotificationPermission] = useState<NotificationPermissionState>('unsupported');
  const [notificationPending, setNotificationPending] = useState(false);
  const [desktopPermission, setDesktopPermission] = useState(() => desktopChatPermission());
  useEffect(() => {
    if (!isNativePlatform()) return;
    void notificationService.getPermissionState().then(setNotificationPermission);
    return notificationService.subscribeToEvents((event) => {
      if (event.type === 'permission') setNotificationPermission(event.state);
    });
  }, []);
  useEffect(() => {
    if (profile.data)
      setForm((current) => ({
        ...current,
        username: profile.data.username,
        avatar_url: profile.data.avatar_url?.startsWith("/")
          ? profile.data.avatar_url
          : "",
        locale: profile.data.locale,
        phone_number: profile.data.phone_number ?? "",
        birthday: profile.data.birthday ?? "",
        work_direction: profile.data.work_direction ?? "",
        work_branch: profile.data.work_branch ?? "",
      }));
  }, [profile.data]);
  useEffect(() => {
    if (!passwordOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPasswordOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [passwordOpen]);
  const submitProfile = async (event: React.FormEvent) => {
    event.preventDefault();
    await update.mutateAsync({
      username: form.username,
      avatar_url: form.avatar_url || null,
      locale: form.locale,
      phone_number: form.phone_number || null,
      birthday: form.birthday || null,
      work_direction: form.work_direction || null,
      work_branch: form.work_branch || null,
      current_password: form.username_password || undefined,
    });
  };
  const submitPassword = async (event: React.FormEvent) => {
    event.preventDefault();
    await changePassword.mutateAsync({
      current_password: form.current_password || undefined,
      new_password: form.new_password,
    });
    setForm((current) => ({
      ...current,
      current_password: "",
      new_password: "",
    }));
    setPasswordOpen(false);
  };
  const linkTelegram = () => {
    const initData = (window as any).Telegram?.WebApp?.initData;
    if (initData) telegramLink.mutate(initData);
    else window.location.href = "/tg";
  };
  const chooseUpload = async (file?: File) => {
    if (!file) return;
    const result = await uploadAvatar.mutateAsync(file);
    setForm((current) => ({ ...current, avatar_url: result.avatar_url }));
  };
  const needsPasswordSetup = profile.data?.requires_password_setup ?? false;
  const requestNotifications = async () => {
    setNotificationPending(true);
    try {
      setNotificationPermission(await notificationService.requestPermissionAndRegister());
    } finally {
      setNotificationPending(false);
    }
  };
  const enableDesktopAlerts = async () => {
    setNotificationPending(true);
    try {
      const permission = await requestDesktopChatPermission();
      setDesktopPermission(permission);
      if (permission === 'granted') {
        await updateChatNotifications.mutateAsync({ desktop_alerts_enabled: true, sound_enabled: chatNotifications.data?.sound_enabled ?? true });
        if (chatNotifications.data?.sound_enabled ?? true) await previewChatSound();
      }
    } finally {
      setNotificationPending(false);
    }
  };
  return (
    <div className="profile-page">
      <div className="view-toolbar">
        <div>
          <h2>Миний профайл</h2>
          <p>Хувийн болон ажлын мэдээллээ удирдана.</p>
        </div>
      </div>
      <div className="profile-grid">
        <section className="panel profile-card">
          <div className="profile-avatar">
            {form.avatar_url ? (
              <img src={resolvePublicAssetUrl(form.avatar_url) || undefined} alt="Профайл зураг" />
            ) : (
              <UserRound />
            )}
          </div>
          <div>
            <span className="eyebrow">Админаас оноосон нэр</span>
            <h2>{profile.data?.name ?? "…"}</h2>
            <p>
              {profile.data?.telegram_connected
                ? `Telegram: @${profile.data.telegram_username || "connected"}`
                : "Telegram холбогдоогүй"}
            </p>
            <button
              type="button"
              className="secondary-action compact" 
              onClick={linkTelegram}
              disabled={telegramLink.isPending}
            >
              {profile.data?.telegram_connected
                ? "Telegram дахин холбох"
                : "Telegram холбох"}
            </button>
            <small>
              Энд оруулсан ажлын мэдээлэл байгууллагын ажилтнуудад харагдана.
            </small>
          </div>
        </section>
        {isNativePlatform() && (
          <section className="panel native-notification-settings">
            <div><Bell size={20} /><div><strong>Push мэдэгдэл</strong><small>Төхөөрөмж дээрх ажлын мэдэгдлийг удирдана.</small></div></div>
            <button
              type="button"
              className="secondary-action compact"
              onClick={requestNotifications}
              disabled={notificationPending || notificationPermission === 'granted' || notificationPermission === 'denied'}
            >
              {notificationPermission === 'granted' ? 'Идэвхтэй' : notificationPermission === 'denied' ? 'Тохиргооноос зөвшөөрнө үү' : notificationPending ? 'Хүлээнэ үү…' : 'Push мэдэгдэл зөвшөөрөх'}
            </button>
          </section>
        )}
        {!isNativePlatform() && (
          <section className="panel native-notification-settings chat-notification-settings">
            <div><Bell size={20} /><div><strong>Чатын desktop мэдэгдэл</strong><small>Апп нуугдсан эсвэл minimize үед зурагт мэдэгдэл болон дуу ашиглана.</small></div></div>
            <div className="chat-notification-actions">
              <button type="button" className="secondary-action compact" onClick={enableDesktopAlerts} disabled={notificationPending || desktopPermission === 'denied'}>
                {desktopPermission === 'denied' ? 'Browser тохиргооноос зөвшөөрнө үү' : chatNotifications.data?.desktop_alerts_enabled && desktopPermission === 'granted' ? 'Идэвхтэй' : notificationPending ? 'Хүлээнэ үү…' : 'Desktop мэдэгдэл зөвшөөрөх'}
              </button>
              {desktopPermission === 'granted' && <label className="chat-sound-toggle"><input type="checkbox" checked={chatNotifications.data?.sound_enabled ?? true} onChange={(event) => updateChatNotifications.mutate({ desktop_alerts_enabled: chatNotifications.data?.desktop_alerts_enabled ?? true, sound_enabled: event.target.checked })} /><span>Мэдэгдлийн дуу</span><button type="button" onClick={() => previewChatSound()}>Сонсох</button></label>}
            </div>
          </section>
        )}
        <form className="panel profile-form" onSubmit={submitProfile}>
          <div className="memoji-picker">
            <div>
              <strong>Memoji зураг сонгох</strong>
              <small>256×256 PNG</small>
            </div>
            <div>
              {MEMOJI_OPTIONS.map((url, index) => (
                <button
                  type="button"
                  key={url}
                  className={form.avatar_url === url ? "selected" : ""}
                  onClick={() => setForm({ ...form, avatar_url: url })}
                  aria-label={`Memoji ${index + 1} зураг сонгох`}
                >
                  <img src={url} alt="" />
                </button>
              ))}
            </div>
          </div>
          <label className="avatar-upload">
            <span>Өөрийн зураг оруулах</span>
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(event) => chooseUpload(event.target.files?.[0])}
              disabled={uploadAvatar.isPending}
            />
            <span>
              <ImageUp size={16} />
              {uploadAvatar.isPending
                ? "Шалгаж байна…"
                : "PNG, JPEG, WebP · хамгийн ихдээ 256×256, 2 MB"}
            </span>
          </label>
          <label>
            Утас
            <input
              value={form.phone_number}
              onChange={(event) =>
                setForm({ ...form, phone_number: event.target.value })
              }
            />
          </label>
          <label>
            Төрсөн өдөр
            <input
              type="date"
              value={form.birthday}
              onChange={(event) =>
                setForm({ ...form, birthday: event.target.value })
              }
            />
          </label>
          <label>
            Ажлын чиглэл
            <input
              value={form.work_direction}
              onChange={(event) =>
                setForm({ ...form, work_direction: event.target.value })
              }
            />
          </label>
          <label>
            Алба
            <input
              value={form.work_branch}
              onChange={(event) =>
                setForm({ ...form, work_branch: event.target.value })
              }
            />
          </label>
          <label>
            Нэвтрэх нэр
            <input
              value={form.username}
              onChange={(event) =>
                setForm({ ...form, username: event.target.value })
              }
              required
              disabled={needsPasswordSetup}
            />
          </label>
          {profile.data && form.username !== profile.data.username && (
            <label>
              Нэвтрэх нэр солих баталгаажуулах нууц үг
              <input
                type="password"
                autoComplete="current-password"
                value={form.username_password}
                onChange={(event) =>
                  setForm({ ...form, username_password: event.target.value })
                }
                required
              />
            </label>
          )}
          <DropdownSelect label="Хэл" value={form.locale} onChange={(locale) => setForm({ ...form, locale })} options={[{ value: "mn", label: "Монгол" }, { value: "en", label: "English" }, { value: "ru", label: "Русский" }]} fullWidth />
          <div className="profile-actions">
            <button
              className="primary-action profile-save"
              disabled={update.isPending}
            >
              <Save size={16} />
              Профайл хадгалах
            </button>
            <button
              type="button"
              className="secondary-action profile-password-trigger"
              onClick={() => setPasswordOpen(true)}
            >
              <KeyRound size={16} />
              {needsPasswordSetup ? "Нууц үг үүсгэх" : "Нууц үг солих"}
            </button>
          </div>
        </form>
      </div>
      {passwordOpen && (
        <div
          className="sheet-backdrop profile-password-backdrop"
          onMouseDown={() => setPasswordOpen(false)}
        >
          <form
            className="panel profile-password-modal"
            onSubmit={submitPassword}
            role="dialog"
            aria-modal="true"
            aria-labelledby="profile-password-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <span className="eyebrow">Профайлын аюулгүй байдал</span>
                <h3 id="profile-password-title">
                  {needsPasswordSetup ? "Нууц үг үүсгэх" : "Нууц үг солих"}
                </h3>
                <p>
                  {needsPasswordSetup
                    ? "Энэ хэрэглэгчийн нэрээр нууц үг үүсгэнэ."
                    : "Нэвтрэх нэр эсвэл нууц үг солиход одоогийн нууц үгээ оруулна."}
                </p>
              </div>
              <button
                type="button"
                className="profile-password-close"
                onClick={() => setPasswordOpen(false)}
                aria-label="Хаах"
              >
                <X size={18} />
              </button>
            </header>
            {!needsPasswordSetup && (
              <label>
                Одоогийн нууц үг
                <input
                  autoFocus
                  type="password"
                  autoComplete="current-password"
                  value={form.current_password}
                  onChange={(event) =>
                    setForm({ ...form, current_password: event.target.value })
                  }
                />
              </label>
            )}
            <label>
              Шинэ нууц үг
              <input
                autoFocus={needsPasswordSetup}
                type="password"
                minLength={10}
                autoComplete="new-password"
                value={form.new_password}
                onChange={(event) =>
                  setForm({ ...form, new_password: event.target.value })
                }
                required
              />
            </label>
            <footer>
              <button
                type="button"
                className="secondary-action"
                onClick={() => setPasswordOpen(false)}
              >
                Цуцлах
              </button>
              <button
                className="primary-action"
                disabled={changePassword.isPending}
              >
                <Save size={16} />
                Хадгалах
              </button>
            </footer>
          </form>
        </div>
      )}
    </div>
  );
}
