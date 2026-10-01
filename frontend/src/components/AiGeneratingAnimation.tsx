import { useTranslation } from 'react-i18next'
export function AiGeneratingAnimation({ className = '' }: { className?: string }) {
  const { t } = useTranslation()
  return (
    <div className={`ai-generating-animation ${className}`.trim()} role="status" aria-label={t('assistant.generating')}>
      <span className="ai-generating-spark spark-one" />
      <span className="ai-generating-spark spark-two" />
      <span className="ai-generating-spark spark-three" />
      <span className="ai-generating-spark spark-four" />
      <span className="sr-only">{t('assistant.generatingDots')}</span>
    </div>
  )
}
