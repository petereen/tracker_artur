import { useAuthStore } from '../store/auth'

const NAV = [
  { id: 'dashboard',  label: 'Хянах самбар',  icon: '▦' },
  { id: 'employees',  label: 'Ажилтнууд',     icon: '◉' },
  { id: 'tasks',      label: 'Даалгаврууд',   icon: '✓' },
  { id: 'questions',  label: 'Асуултууд',     icon: '≡' },
  { id: 'schedule',   label: 'Хуваарь',       icon: '◷' },
  { id: 'journal',    label: 'Бүртгэл',       icon: '☰' },
  { id: 'manager',    label: 'Удирдлага',     icon: '◎' },
  { id: 'knowledge',  label: 'Компанийн мэдлэг', icon: '◆' },
  { id: 'onboarding', label: 'Танилцуулга',   icon: '▷' },
]

export function Sidebar({ active, onNav }: { active: string; onNav: (id: string) => void }) {
  const logout = useAuthStore((s) => s.logout)

  return (
    <div className="admin-sidebar w-[220px] bg-surface border-r border-border flex flex-col flex-shrink-0 h-screen sticky top-0">
      <div className="px-5 pt-5 pb-4">
        <img
          src="/oyuns-aio-logo.png"
          alt="OYUNS All-in-One"
          className="w-full h-auto max-h-9 object-contain object-left"
        />
      </div>
      <div className="h-px bg-border mx-4 mb-3" />
      <nav className="flex-1 px-2.5 overflow-y-auto">
        {NAV.map((n) => (
          <button key={n.id} onClick={() => onNav(n.id)}
            className={`w-full flex items-center gap-2.5 px-3 py-[9px] rounded-lg border-none text-[13px] text-left cursor-pointer transition-all mb-0.5
              ${active === n.id ? 'bg-accent-dim text-accent font-semibold' : 'bg-transparent text-muted font-normal hover:bg-surface2'}`}>
            <span className="text-sm opacity-80">{n.icon}</span>
            {n.label}
          </button>
        ))}
      </nav>
      <div className="px-5 py-4 border-t border-border">
        <div className="flex items-center gap-2.5">
          <div className="w-[30px] h-[30px] rounded-full bg-surface3 flex items-center justify-center text-[13px] font-semibold text-muted flex-shrink-0">А</div>
          <div className="flex-1 min-w-0">
            <div className="text-[13px] font-medium truncate">Администратор</div>
            <button onClick={logout} className="text-[11px] text-muted hover:text-red cursor-pointer bg-transparent border-none">Гарах</button>
          </div>
        </div>
      </div>
    </div>
  )
}
