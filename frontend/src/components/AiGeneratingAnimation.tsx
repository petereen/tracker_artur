export function AiGeneratingAnimation({ className = '' }: { className?: string }) {
  return (
    <div className={`ai-generating-animation ${className}`.trim()} role="status" aria-label="AI хариу бэлтгэж байна">
      <span className="ai-generating-spark spark-one" />
      <span className="ai-generating-spark spark-two" />
      <span className="ai-generating-spark spark-three" />
      <span className="ai-generating-spark spark-four" />
      <span className="sr-only">AI хариу бэлтгэж байна…</span>
    </div>
  )
}
