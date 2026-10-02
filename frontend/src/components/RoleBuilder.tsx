import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
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
import { catalogText } from '../utils/labelMap'

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
    {catalog.modules.map((module) => <section key={module.key} className="role-matrix-module" aria-label={catalogText(`cat.module.${module.key}`, module.label)}>
      <Text weight="semibold">{catalogText(`cat.module.${module.key}`, module.label)}</Text>
      {module.resources.map((resource) => {
        const keys = resource.actions.map((action) => key(resource.key, action.key))
        const count = keys.filter((item) => selected.has(item)).length
        return <div key={resource.key} className="role-matrix-row">
          <CheckboxInput label={catalogText(`cat.resource.${resource.key}`, resource.label)} value={count === keys.length ? true : count === 0 ? false : 'indeterminate'} isDisabled={disabled} onChange={() => setMany(keys, count !== keys.length)} />
          <div className="role-matrix-actions">
            {resource.actions.map((action) => <CheckboxInput key={action.key} label={catalogText(`cat.action.${action.key}`, action.label)} value={selected.has(key(resource.key, action.key))} isDisabled={disabled}
              onChange={(on) => setMany([key(resource.key, action.key)], on)} />)}
          </div>
        </div>
      })}
    </section>)}
  </VStack>
}

function Assignments({ role }: { role: ERPAccessRole }) {
  const { t } = useTranslation()
  const accounts = useManagedAccounts(); const teams = useTeams()
  const assignAccount = useAssignERPAccountRole(); const assignTeam = useAssignERPTeamRole()
  const unassignAccount = useUnassignERPAccountRole(); const unassignTeam = useUnassignERPTeamRole()
  const accountLabel = (id: number) => accounts.data?.find((account) => account.id === id)?.email || `#${id}`
  const run = (promise: Promise<unknown>, done: string) => promise.then(() => toast.success(done)).catch((error) => toast.error(errorMessage(error, t('st.rb.actionFailed'))))
  const freeAccounts = (accounts.data ?? []).filter((account) => account.status !== 'disabled' && !role.account_assignments.some((item) => item.account_id === account.id))
  const freeTeams = (teams.data ?? []).filter((team) => !role.team_assignments.some((item) => item.team_id === team.id))
  return <VStack gap={3}>
    <Heading level={4}>{t('st.rb.whoAssigned')}</Heading>
    {!role.account_assignments.length && !role.team_assignments.length && <Text type="supporting">{t('st.rb.noAssignments')}</Text>}
    <HStack gap={2} wrap="wrap">
      {role.account_assignments.map((item) => <Token key={`a-${item.id}`} label={item.label || accountLabel(item.account_id)} onRemove={() => run(unassignAccount.mutateAsync({ roleId: role.id, assignmentId: item.id }), t('st.rb.unassignedUser'))} />)}
      {role.team_assignments.map((item) => <Token key={`t-${item.id}`} color="blue" label={t('st.rb.teamToken', { name: item.label || item.team_id })} onRemove={() => run(unassignTeam.mutateAsync({ roleId: role.id, assignmentId: item.id }), t('st.rb.unassignedTeam'))} />)}
    </HStack>
    <HStack gap={2} wrap="wrap">
      <Selector label={t('st.rb.assignToUser')} placeholder={t('st.rb.pickUser')} options={freeAccounts.map((account) => ({ value: String(account.id), label: account.email }))} value=""
        onChange={(value) => value && run(assignAccount.mutateAsync({ roleId: role.id, account_id: Number(value) }), t('st.rb.assignedUser'))} />
      <Selector label={t('st.rb.assignToTeam')} placeholder={t('st.rb.pickTeam')} options={freeTeams.map((team) => ({ value: String(team.id), label: team.name }))} value=""
        onChange={(value) => value && run(assignTeam.mutateAsync({ roleId: role.id, team_id: Number(value) }), t('st.rb.assignedTeam'))} />
    </HStack>
    <Text type="supporting">{t('st.rb.applyHint')}</Text>
  </VStack>
}

/**
 * Real role creator: a role = platform access levels (manager, HR, …) plus
 * module permissions the APIs enforce, assigned to people or teams.
 */
export function RoleBuilder() {
  const { t } = useTranslation()
  const catalog = useERPRoleCatalog(); const roles = useERPAccessRoles()
  const create = useCreateERPAccessRole(); const update = useUpdateERPAccessRole(); const clone = useCloneERPAccessRole()
  const deactivate = useDeactivateERPAccessRole(); const activate = useActivateERPAccessRole(); const remove = useDeleteERPAccessRole()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const selected = roles.data?.find((role) => role.id === selectedId) ?? null
  const baseline = useMemo(() => (selected && catalog.data ? toDraft(selected, catalog.data) : EMPTY), [selected, catalog.data])
  useEffect(() => { setDraft(baseline) }, [baseline])

  if (catalog.isLoading || roles.isLoading) return <Text type="supporting">{t('st.common.loading')}</Text>
  if (catalog.isError || roles.isError || !catalog.data) return <Banner status="error" title={t('st.rb.loadFailed')} description={t('st.rb.adminRequired')} />

  const readOnly = Boolean(selected?.is_system)
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline)
  const empty = !draft.systemRoles.length && !draft.capabilities.length && !draft.extras.length
  const customRoles = (roles.data ?? []).filter((role) => !role.is_system)
  const templates = (roles.data ?? []).filter((role) => role.is_system)
  const save = async () => {
    if (!draft.name.trim()) { toast.error(t('st.rb.nameRequired')); return }
    if (empty) { toast.error(t('st.rb.pickPermission')); return }
    try {
      const saved = selected ? await update.mutateAsync({ id: selected.id, ...payload(draft) }) : await create.mutateAsync(payload(draft))
      toast.success(selected ? t('st.rb.saved') : t('st.rb.created'))
      setSelectedId(saved.id)
    } catch (error) { toast.error(errorMessage(error, t('st.rb.saveFailed'))) }
  }
  const act = async (promise: Promise<unknown>, done: string, after?: () => void) => {
    try { await promise; toast.success(done); after?.() } catch (error) { toast.error(errorMessage(error, t('st.rb.actionFailed'))) }
  }
  const roleButton = (role: ERPAccessRole) => <button key={role.id} type="button" className={role.id === selectedId ? 'active' : ''} onClick={() => setSelectedId(role.id)}>
    <span>{role.name}</span>
    <small>{role.is_system ? t('st.rb.template') : role.is_active ? t('st.rb.active') : t('st.rb.inactive')} · {t('st.rb.assignments', { n: role.account_assignments.length + role.team_assignments.length })}</small>
  </button>

  return <Card padding={5}>
    <div className="role-builder">
      <aside className="role-builder-list" aria-label={t('st.rb.listAria')}>
        <button type="button" className={selectedId === null ? 'active' : ''} onClick={() => setSelectedId(null)}><span><Plus size={14} /> {t('st.rb.newRole')}</span></button>
        {customRoles.length > 0 && <p className="role-builder-group">{t('st.rb.orgRoles')}</p>}
        {customRoles.map(roleButton)}
        {templates.length > 0 && <p className="role-builder-group">{t('st.rb.templates')}</p>}
        {templates.map(roleButton)}
      </aside>
      <VStack gap={4}>
        <HStack gap={2} vAlign="center" wrap="wrap">
          <ShieldCheck size={18} aria-hidden />
          <Heading level={3}>{selected ? selected.name : t('st.rb.newRole')}</Heading>
          {selected?.is_system && <Token size="sm" color="gray" label={t('st.rb.systemTemplate')} />}
          {selected && !selected.is_active && <Token size="sm" color="red" label={t('st.rb.inactive')} />}
        </HStack>
        {readOnly && <Banner status="info" collapsible={false} title={t('st.rb.readOnlyTitle')} description={t('st.rb.readOnlyDesc')} />}
        <HStack gap={3} wrap="wrap">
          <TextInput label={t('st.rb.name')} value={draft.name} onChange={(name) => setDraft({ ...draft, name })} isRequired isDisabled={readOnly} placeholder={t('st.rb.namePlaceholder')} />
          <TextInput label={t('st.rb.description')} value={draft.description} onChange={(description) => setDraft({ ...draft, description })} isDisabled={readOnly} placeholder={t('st.rb.descriptionPlaceholder')} />
        </HStack>
        <VStack gap={2}>
          <Heading level={4}>{t('st.rb.platformPerms')}</Heading>
          <Text type="supporting">{t('st.rb.platformPermsHint')}</Text>
          <div className="role-system-grid">
            {catalog.data.system_roles.map((role) => <CheckboxInput key={role.key} label={catalogText(`cat.sysRole.${role.key}.label`, role.label)} description={catalogText(`cat.sysRole.${role.key}.description`, role.description)} isDisabled={readOnly}
              value={draft.systemRoles.includes(role.key)}
              onChange={(on) => setDraft({ ...draft, systemRoles: on ? [...draft.systemRoles, role.key].sort() : draft.systemRoles.filter((item) => item !== role.key) })} />)}
          </div>
        </VStack>
        <VStack gap={2}>
          <Heading level={4}>{t('st.rb.modulePerms')}</Heading>
          <Text type="supporting">{t('st.rb.modulePermsHint')}</Text>
          <PermissionMatrix catalog={catalog.data} value={draft.capabilities} disabled={readOnly} onChange={(capabilities) => setDraft({ ...draft, capabilities })} />
          {draft.extras.length > 0 && <Text type="supporting">{t('st.rb.extras', { list: draft.extras.join(', ') })}</Text>}
        </VStack>
        <HStack gap={2} wrap="wrap">
          {!readOnly && <Button label={selected ? t('st.common.save') : t('st.rb.createRole')} variant="primary" isDisabled={(!dirty && Boolean(selected)) || !draft.name.trim() || empty} isLoading={create.isPending || update.isPending} onClick={save} />}
          {!readOnly && dirty && <Button label={t('st.common.revert')} onClick={() => setDraft(baseline)} />}
          {selected && <Button label={readOnly ? t('st.rb.copyEdit') : t('st.rb.copy')} isLoading={clone.isPending} onClick={() => act(clone.mutateAsync(selected.id).then((copy) => setSelectedId(copy.id)), t('st.rb.copied'))} />}
          {selected && !readOnly && (selected.is_active
            ? <Button label={t('st.rb.deactivate')} isLoading={deactivate.isPending} onClick={() => act(deactivate.mutateAsync(selected.id), t('st.rb.deactivated'))} />
            : <Button label={t('st.rb.activate')} isLoading={activate.isPending} onClick={() => act(activate.mutateAsync(selected.id), t('st.rb.activated'))} />)}
          {selected && !readOnly && <Button label={t('st.common.delete')} variant="destructive" icon={<X size={14} />} isLoading={remove.isPending}
            onClick={() => { if (window.confirm(t('st.rb.confirmDelete', { name: selected.name }))) void act(remove.mutateAsync(selected.id), t('st.rb.deleted'), () => setSelectedId(null)) }} />}
        </HStack>
        {selected && <Assignments role={selected} />}
      </VStack>
    </div>
  </Card>
}
