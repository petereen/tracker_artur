import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

const resources = {
  mn: { translation: {
    'nav.today': 'Өнөөдөр', 'nav.projects': 'Төслүүд', 'nav.tasks': 'Даалгавар', 'nav.calendar': 'Календарь', 'nav.reports': 'Тайлан',
    'nav.capacity': 'Багийн ачаалал', 'nav.okrs': 'Зорилго', 'nav.analytics': 'Үзүүлэлт', 'nav.settings': 'Тохиргоо',
    'action.search': 'Хайх', 'action.open': 'Нээх', 'action.logout': 'Гарах',
  } },
  en: { translation: {
    'nav.today': 'Today', 'nav.projects': 'Projects', 'nav.tasks': 'Tasks', 'nav.calendar': 'Calendar', 'nav.reports': 'Reports',
    'nav.capacity': 'Team capacity', 'nav.okrs': 'Goals', 'nav.analytics': 'Analytics', 'nav.settings': 'Settings',
    'action.search': 'Search', 'action.open': 'Open', 'action.logout': 'Log out',
  } },
  ru: { translation: {
    'nav.today': 'Сегодня', 'nav.projects': 'Проекты', 'nav.tasks': 'Задачи', 'nav.calendar': 'Календарь', 'nav.reports': 'Отчёты',
    'nav.capacity': 'Загрузка команды', 'nav.okrs': 'Цели', 'nav.analytics': 'Аналитика', 'nav.settings': 'Настройки',
    'action.search': 'Поиск', 'action.open': 'Открыть', 'action.logout': 'Выйти',
  } },
}

i18n.use(initReactI18next).init({ resources, lng: 'mn', fallbackLng: 'mn', interpolation: { escapeValue: false } })

export default i18n
