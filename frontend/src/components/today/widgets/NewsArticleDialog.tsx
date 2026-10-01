import { useTranslation } from 'react-i18next'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { Markdown } from '@astryxdesign/core/Markdown'
import { ScrollableArea } from '@astryxdesign/core/ScrollableArea'
import { VStack } from '@astryxdesign/core/VStack'
import type { Announcement } from '../../../api/today'
import { resolvePublicAssetUrl } from '../../../platform/runtime'
import { intlLocale } from '../../../utils/locale'

/** Full announcement: cover image, author/date, Markdown body and image gallery. */
export function NewsArticleDialog({ article, onClose }: { article: Announcement; onClose: () => void }) {
  const { t } = useTranslation()
  const images = [article.cover_url, ...(article.image_urls ?? [])].map(resolvePublicAssetUrl).filter((url): url is string => Boolean(url))
  const meta = [article.author_name, article.category, new Date(article.published_at).toLocaleString(intlLocale(), { dateStyle: 'medium', timeStyle: 'short' })].filter(Boolean).join(' · ')
  return (
    <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={720} maxHeight="88dvh">
      <DialogHeader title={article.title} subtitle={meta} onOpenChange={(open) => { if (!open) onClose() }} />
      <ScrollableArea label={t('today.news.content')} minHeight={0} overscroll="contain">
        <VStack gap={4} padding={4}>
          {images[0] && <img className="today-news-cover" src={images[0]} alt="" loading="lazy" />}
          {article.body ? <Markdown density="compact" headingLevelStart={3} contentWidth="100%">{article.body}</Markdown> : <p>{article.summary}</p>}
          {images.length > 1 && <span className="today-news-gallery">{images.slice(1).map((url) => <a key={url} href={url} target="_blank" rel="noreferrer"><img src={url} alt="" loading="lazy" /></a>)}</span>}
        </VStack>
      </ScrollableArea>
    </Dialog>
  )
}
