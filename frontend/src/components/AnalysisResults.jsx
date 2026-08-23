import { motion } from 'framer-motion'

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.04 },
  },
}

const item = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0 },
}

function normalizedText(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function normalizedList(value) {
  if (!Array.isArray(value)) return []
  return value.map(normalizedText).filter(Boolean)
}

function TextSection({ title, text }) {
  if (!text) return null

  return (
    <motion.section
      variants={item}
      className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm sm:p-6"
    >
      <h3 className="mb-3 text-lg font-semibold text-slate-800">{title}</h3>
      <p className="text-slate-700 leading-relaxed">{text}</p>
    </motion.section>
  )
}

function ListSection({ title, items }) {
  if (items.length === 0) return null

  return (
    <motion.section
      variants={item}
      className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm sm:p-6"
    >
      <h3 className="mb-3 text-lg font-semibold text-slate-800">{title}</h3>
      <ul className="space-y-2 text-slate-700">
        {items.map((entry, index) => (
          <li key={`${title}-${index}`} className="flex gap-3 leading-relaxed">
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-indigo-500" />
            <span>{entry}</span>
          </li>
        ))}
      </ul>
    </motion.section>
  )
}

export function AnalysisResults({ data }) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null

  const summary = normalizedText(data.summary)
  const purpose = normalizedText(data.purpose)
  const targetAudience = normalizedText(data.target_audience)
  const keyTopics = normalizedList(data.key_topics)
  const offerings = normalizedList(data.offerings)
  const notableClaims = normalizedList(data.notable_claims)
  const contentStrengths = normalizedList(data.content_strengths)
  const contentGaps = normalizedList(data.content_gaps)
  const analysis = normalizedText(data.analysis)

  const hasContent =
    summary ||
    purpose ||
    targetAudience ||
    analysis ||
    keyTopics.length > 0 ||
    offerings.length > 0 ||
    notableClaims.length > 0 ||
    contentStrengths.length > 0 ||
    contentGaps.length > 0

  if (!hasContent) return null

  return (
    <motion.div
      className="mt-10 sm:mt-12"
      variants={container}
      initial="hidden"
      animate="show"
    >
      <h2 className="mb-6 text-xl font-semibold text-slate-800 sm:text-2xl">
        Анализ содержания страницы
      </h2>
      <div className="space-y-5">
        <TextSection title="Краткое резюме" text={summary} />
        <TextSection title="Назначение" text={purpose} />
        <TextSection title="Целевая аудитория" text={targetAudience} />
        <ListSection title="Ключевые темы" items={keyTopics} />
        <ListSection title="Предложения" items={offerings} />
        <ListSection title="Заявления страницы" items={notableClaims} />
        <ListSection title="Сильные стороны содержания" items={contentStrengths} />
        <ListSection title="Пробелы и неясные моменты" items={contentGaps} />
        <TextSection title="Общий анализ" text={analysis} />
      </div>
    </motion.div>
  )
}
