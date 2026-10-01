import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { Plus, ShieldCheck, X } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { CheckboxInput } from '@astryxdesign/core/CheckboxInput'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { Selector } from '@astryxdesign/core/Selector'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  type ERPAccessRole, type ERPRoleCatalog,
  useActivateERPAccessRole, useAssignERPAccountRole, useAssignERPTeamRole, useCloneERPAccessRole, useCreateERPAccessRole,
  useDeactivateERPAccessRole, useDeleteERPAccessRole, useERPAccessRoles, useERPRoleCatalog, useManagedAccounts, useTeams,
  useUnassignERPAccountRole, useUnassignERPTeamRole, useUpdateERPAccessRole,
} from '../api/enterprise'

type Draft = { name: string; description: string; systemRoles: string[]; capabilities: string[]; extras: string[] }
const EMPTY: Draft = { name: '', description: '', systemRoles: [], capabilities: [], extras: [] }
const key = (resource: string, action: string) => `${resource}.${action}`

function errorMessage(error: any, fallback: string) {
  const detail = error?.response?.data?.detail
  return (typeof detail === 'string' ? detail : detail?.message || detail?.code) || fallback
}

/**
 * Stored capabilities → editor state. ``resource.*`` and ``*.*`` (seeded
 * templates) expand to the catalog's actions; grants outside the catalog
 * (retired document types) are kept untouched as ``extras``.
 */
function toDraft(role: ERPAccessRole, catalog: ERPRoleCatalog): Draft {
  const known = new Map<string, string[]>()
  for (const module of catalog.modules) for (const resource of module.resources) known.set(resource.key, resource.actions.map((action) => action.key))
  const capabilities = new Set<string>()
  const extras: string[] = []
  for (const { resource, action } of role.capabilities) {
    if (resource === '*') { known.forEach((actions, item) => actions.forEach((name) => capabilities.add(key(item, name)))); if (action === '*') continue }
    const actions = known.get(resource)
    if (!actions) { extras.push(key(resource, action)); continue }
    if (action === '*') actions.forEach((name) => capabilities.add(key(resource, name)))
    else if (actions.includes(action)) capabilities.add(key(resource, action))
  }
  if (role.capabilities.some((item) => item.resource === '*' && item.action === '*')) extras.push('*.*')
  return { name: role.name, description: role.description || '', systemRoles: role.system_roles ?? [], capabilities: [...capabilities], extras }
}

function payload(draft: Draft) {
  return {
    name: draft.name.trim(),
    description: draft.description.trim() || undefined,
    system_roles: draft.systemRoles,
    capabilities: [...draft.capabilities, ...draft.extras].map((item) => { const at = item.lastIndexOf('.'); return { resource: item.slice(0, at), action: item.slice(at + 1) } }),
  }
}

function PermissionMatrix({ catalog, value, onChange, disabled }: { catalog: ERPRoleCatalog; value: string[]; onChange: (next: string[]) => void; disabled: boolean }) {
  const selected = new Set(value)
  const setMany = (keys: string[], on: boolean) => {
    const next = new Set(selected)
    keys.forEach((item) => (on ? next.add(item) : next.delete(item)))
    onChange([...next])
  }
  return <VStack gap={3}>
    {catalog.modules.map((module) => <section key={module.key} className="role-matrix-module" aria-label={module.label}>
      <Text weight="semibold">{module.label}</Text>
      {module.resources.map((resource) => {
        const keys = resource.actions.map((action) => key(resource.key, action.key))
        const count = keys.filter((item) => selected.has(item)).length
        return <div key={resource.key} className="role-matrix-row">
          <CheckboxInput label={resource.label} value={count === keys.length ? true : count === 0 ? false : 'indeterminate'} isDisabled={disabled} onChange={() => setMany(keys, count !== keys.length)} />
          <div className="role-matrix-actions">
            {resource.actions.map((action) => <CheckboxInput key={action.key} label={action.label} value={selected.has(key(resource.key, action.key))} isDisabled={disabled}
              onChange={(on) => setMany([key(resource.key, action.key)], on)} />)}
          </div>
        </div>
      })}
    </section>)}
  </VStack>
}

function Assignments({ role }: { role: ERPAccessRole }) {
  const accounts = useManagedAccounts(); const teams = useTeams()
  const assignAccount = useAssignERPAccountRole(); const assignTeam = useAssignERPTeamRole()
  const unassignAccount = useUnassignERPAccountRole(); const unassignTeam = useUnassignERPTeamRole()
  const accountLabel = (id: number) => accounts.data?.find((account) => account.id === id)?.email || `#${id}`
  const run = (promise: Promise<unknown>, done: string) => promise.then(() => toast.success(done)).catch((error) => toast.error(errorMessage(error, 'Үйлдэл амжилтгүй')))
  const freeAccounts = (accounts.data ?? []).filter((account) => account.status !== 'disabled' && !role.account_assignments.some((item) => item.account_id === account.id))
  const freeTeams = (teams.data ?? []).filter((team) => !role.team_assignments.some((item) => item.team_id === team.id))
  return <VStack gap={3}>
    <Heading level={4}>Хэнд оноосон</Heading>
    {!role.account_assignments.length && !role.team_assignments.length && <Text type="supporting">Одоогоор хэнд ч оноогоогүй. Хэрэглэгч эсвэл баг сонгож онооно уу.</Text>}
    <HStack gap={2} wrap="wrap">
      {role.account_assignments.map((item) => <Token key={`a-${item.id}`} label={item.label || accountLabel(item.account_id)} onRemove={() => run(unassignAccount.mutateAsync({ roleId: role.id, assignmentId: item.id }), 'Хэрэглэгчээс хаслаа')} />)}
      {role.team_assignments.map((item) => <Token key={`t-${item.id}`} color="blue" label={`Баг: ${item.label || item.team_id}`} onRemove={() => run(unassignTeam.mutateAsync({ roleId: role.id, assignmentId: item.id }), 'Багаас хаслаа')} />)}
    </HStack>
    <HStack gap={2} wrap="wrap">
      <Selector label="Хэрэглэгчид оноох" placeholder="Хэрэглэгч сонгох…" options={freeAccounts.map((account) => ({ value: String(account.id), label: account.email }))} value=""
        onChange={(value) => value && run(assignAccount.mutateAsync({ roleId: role.id, account_id: Number(value) }), 'Хэрэглэгчид оноолоо')} />
      <Selector label="Багт оноох" placeholder="Баг сонгох…" options={freeTeams.map((team) => ({ value: String(team.id), label: team.name }))} value=""
        onChange={(value) => value && run(assignTeam.mutateAsync({ roleId: role.id, team_id: Number(value) }), 'Багт оноолоо')} />
    </HStack>
    <Text type="supporting">Үүргийн эрх хэрэглэгчийн дараагийн хүсэлтээс (ихэвчлэн хэдэн секундэд) хүчинтэй болно. Багт оноосон үүрэг багийн бүх гишүүнд үйлчилнэ.</Text>
  </VStack>
}

/**
 * Real role creator: a role = platform access levels (manager, HR, …) plus
 * module permissions the APIs enforce, assigned to people or teams.
 */
export function RoleBuilder() {
  const catalog = useERPRoleCatalog(); const roles = useERPAccessRoles()
  const create = useCreateERPAccessRole(); const update = useUpdateERPAccessRole(); const clone = useCloneERPAccessRole()
  const deactivate = useDeactivateERPAccessRole(); const activate = useActivateERPAccessRole(); const remove = useDeleteERPAccessRole()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const selected = roles.data?.find((role) => role.id === selectedId) ?? null
  const baseline = useMemo(() => (selected && catalog.data ? toDraft(selected, catalog.data) : EMPTY), [selected, catalog.data])
  useEffect(() => { setDraft(baseline) }, [baseline])

  if (catalog.isLoading || roles.isLoading) return <Text type="supporting">Ачаалж байна…</Text>
  if (catalog.isError || roles.isError || !catalog.data) return <Banner status="error" title="Үүрэг ба эрхийг ачаалж чадсангүй" description="Админ эрх шаардлагатай." />

  const readOnly = Boolean(selected?.is_system)
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline)
  const empty = !draft.systemRoles.length && !draft.capabilities.length && !draft.extras.length
  const customRoles = (roles.data ?? []).filter((role) => !role.is_system)
  const templates = (roles.data ?? []).filter((role) => role.is_system)
  const save = async () => {
    if (!draft.name.trim()) { toast.error('Үүргийн нэр оруулна уу'); return }
    if (empty) { toast.error('Дор хаяж нэг эрх сонгоно уу'); return }
    try {
      const saved = selected ? await update.mutateAsync({ id: selected.id, ...payload(draft) }) : await create.mutateAsync(payload(draft))
      toast.success(selected ? 'Үүрэг хадгалагдлаа' : 'Шинэ үүрэг үүслээ')
      setSelectedId(saved.id)
    } catch (error) { toast.error(errorMessage(error, 'Үүрэг хадгалагдсангүй')) }
  }
  const act = async (promise: Promise<unknown>, done: string, after?: () => void) => {
    try { await promise; toast.success(done); after?.() } catch (error) { toast.error(errorMessage(error, 'Үйлдэл амжилтгүй')) }
  }
  const roleButton = (role: ERPAccessRole) => <button key={role.id} type="button" className={role.id === selectedId ? 'active' : ''} onClick={() => setSelectedId(role.id)}>
    <span>{role.name}</span>
    <small>{role.is_system ? 'Загвар' : role.is_active ? 'Идэвхтэй' : 'Идэвхгүй'} · {role.account_assignments.length + role.team_assignments.length} оноолт</small>
  </button>

  return <Card padding={5}>
    <div className="role-builder">
      <aside className="role-builder-list" aria-label="Үүргүүд">
        <button type="button" className={selectedId === null ? 'active' : ''} onClick={() => setSelectedId(null)}><span><Plus size={14} /> Шинэ үүрэг</span></button>
        {customRoles.length > 0 && <p className="role-builder-group">Байгууллагын үүрэг</p>}
        {customRoles.map(roleButton)}
        {templates.length > 0 && <p className="role-builder-group">Загвар (хуулж засна)</p>}
        {templates.map(roleButton)}
      </aside>
      <VStack gap={4}>
        <HStack gap={2} vAlign="center" wrap="wrap">
          <ShieldCheck size={18} aria-hidden />
          <Heading level={3}>{selected ? selected.name : 'Шинэ үүрэг'}</Heading>
          {selected?.is_system && <Token size="sm" color="gray" label="Системийн загвар" />}
          {selected && !selected.is_active && <Token size="sm" color="red" label="Идэвхгүй" />}
        </HStack>
        {readOnly && <Banner status="info" collapsible={false} title="Загвар үүргийг шууд засах боломжгүй" description="«Хуулж засах» дарж өөрийн үүрэг болгон өөрчилнө үү." />}
        <HStack gap={3} wrap="wrap">
          <TextInput label="Үүргийн нэр" value={draft.name} onChange={(name) => setDraft({ ...draft, name })} isRequired isDisabled={readOnly} placeholder="Нягтлан бодогч" />
          <TextInput label="Тайлбар" value={draft.description} onChange={(description) => setDraft({ ...draft, description })} isDisabled={readOnly} placeholder="Юунд зориулсан үүрэг вэ" />
        </HStack>
        <VStack gap={2}>
          <Heading level={4}>Платформын эрх</Heading>
          <Text type="supporting">Ажлын орчинд ямар түвшний хандалт өгөхийг сонгоно (даалгавар, тайлан, HR, гэрээ…). Админ эрхийг зөвхөн хэрэглэгчид шууд олгоно.</Text>
          <div className="role-system-grid">
            {catalog.data.system_roles.map((role) => <CheckboxInput key={role.key} label={role.label} description={role.description} isDisabled={readOnly}
              value={draft.systemRoles.includes(role.key)}
              onChange={(on) => setDraft({ ...draft, systemRoles: on ? [...draft.systemRoles, role.key].sort() : draft.systemRoles.filter((item) => item !== role.key) })} />)}
          </div>
        </VStack>
        <VStack gap={2}>
          <Heading level={4}>Модулийн эрх</Heading>
          <Text type="supporting">Зөвхөн систем бодитоор шалгадаг эрхүүд. Лицензэд ороогүй модуль харагдахгүй.</Text>
          <PermissionMatrix catalog={catalog.data} value={draft.capabilities} disabled={readOnly} onChange={(capabilities) => setDraft({ ...draft, capabilities })} />
          {draft.extras.length > 0 && <Text type="supporting">{`Бусад хуучин эрх хадгалагдана: ${draft.extras.join(', ')}`}</Text>}
        </VStack>
        <HStack gap={2} wrap="wrap">
          {!readOnly && <Button label={selected ? 'Хадгалах' : 'Үүрэг үүсгэх'} variant="primary" isDisabled={(!dirty && Boolean(selected)) || !draft.name.trim() || empty} isLoading={create.isPending || update.isPending} onClick={save} />}
          {!readOnly && dirty && <Button label="Буцаах" onClick={() => setDraft(baseline)} />}
          {selected && <Button label={readOnly ? 'Хуулж засах' : 'Хуулах'} isLoading={clone.isPending} onClick={() => act(clone.mutateAsync(selected.id).then((copy) => setSelectedId(copy.id)), 'Хуулбар үүслээ')} />}
          {selected && !readOnly && (selected.is_active
            ? <Button label="Идэвхгүй болгох" isLoading={deactivate.isPending} onClick={() => act(deactivate.mutateAsync(selected.id), 'Идэвхгүй болголоо')} />
            : <Button label="Идэвхжүүлэх" isLoading={activate.isPending} onClick={() => act(activate.mutateAsync(selected.id), 'Идэвхжүүллээ')} />)}
          {selected && !readOnly && <Button label="Устгах" variant="destructive" icon={<X size={14} />} isLoading={remove.isPending}
            onClick={() => { if (window.confirm(`«${selected.name}» үүргийг устгах уу?`)) void act(remove.mutateAsync(selected.id), 'Үүрэг устгагдлаа', () => setSelectedId(null)) }} />}
        </HStack>
        {selected && <Assignments role={selected} />}
      </VStack>
    </div>
  </Card>
}
