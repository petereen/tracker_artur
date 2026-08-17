import { describe, expect, it } from 'vitest'
import { commentMentionQuery, taskActivitySummary, taskCollaborationLabels } from './EnterpriseTasksPage'

describe('task collaboration workspace', () => {
  it('uses Mongolian labels for each compact workspace tab', () => {
    expect(taskCollaborationLabels).toEqual({
      subtasks: 'Дэд ажил',
      checklist: 'Checklist',
      comments: 'Сэтгэгдэл',
      files: 'Файл',
      activity: 'Түүх',
    })
  })

  it('turns audit records into readable history summaries', () => {
    expect(taskActivitySummary({
      entity_type: 'attachment', action: 'created', before: {}, after: { filename: 'brief.pdf' },
    })).toBe('Файл: “brief.pdf” нэмэгдлээ')
    expect(taskActivitySummary({
      entity_type: 'task_check_item', action: 'updated', before: { text: 'Тойм бичих' }, after: {},
    })).toBe('Checklist: “Тойм бичих” шинэчлэгдлээ')
  })

  it('finds an active @mention query at the caret', () => {
    expect(commentMentionQuery('Please @Bat', 12)).toBe('Bat')
    expect(commentMentionQuery('Please @Bat now', 11)).toBe('Bat')
    expect(commentMentionQuery('Please Bat', 11)).toBeNull()
  })
})
