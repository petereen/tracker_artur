import { X } from 'lucide-react'
import { DropdownSelect } from './DropdownSelect'

export type UserOption = { id: number; name: string }

type Props = {
  label: string
  value: number[]
  users: UserOption[]
  onChange: (ids: number[]) => void
  emptyLabel?: string
  allLabel?: string
}

export function UserTagPicker({ label, value, users, onChange, emptyLabel = 'Хэрэглэгч сонгох…', allLabel }: Props) {
  const selected = value.map((id) => users.find((user) => user.id === id)).filter(Boolean) as UserOption[]
  const available = users.filter((user) => !value.includes(user.id))
  const add = (id: number) => onChange([...value, id])
  const remove = (id: number) => onChange(value.filter((item) => item !== id))
  const selectValue = available.length ? '' : '__none__'

  return <div className="user-tag-picker">
    <DropdownSelect label={label} value={selectValue} onChange={(next) => { if (next === '__all__') onChange(users.map((user) => user.id)); else if (next) add(Number(next)) }} disabled={!available.length} options={[{ value: '', label: available.length ? emptyLabel : 'Бүх хэрэглэгч сонгогдсон' }, ...(allLabel ? [{ value: '__all__', label: allLabel }] : []), ...available.map((user) => ({ value: String(user.id), label: user.name }))]} />
    {selected.length > 0 && <div className="user-tag-list" aria-label={`${label} сонгосон хэрэглэгчид`}>
      {selected.map((user) => <span className="user-tag" key={user.id}>
        <span>{user.name}</span>
        <button type="button" onClick={() => remove(user.id)} aria-label={`${user.name} хасах`}><X size={13} /></button>
      </span>)}
    </div>}
  </div>
}
