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

function splitIntoSentences(text) {
  if (!text || typeof text !== 'string') return []
  return text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

export function AnalysisResults({ data }) {
  if (!data || typeof data !== 'object') return null

  const analysis = typeof data.analysis === 'string' ? data.analysis.trim() : ''
  if (!analysis) return null

  const sentences = splitIntoSentences(analysis)

  return (
    <motion.div
      className="mt-10 sm:mt-12"
      variants={container}
      initial="hidden"
      animate="show"
    >
      <h2 className="mb-6 text-xl font-semibold text-slate-800 sm:text-2xl">
        Краткое резюме сайта
      </h2>
      <motion.div
        variants={item}
        className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm sm:p-6"
      >
        {sentences.length > 0 ? (
          <div className="space-y-4">
            {sentences.map((sentence, i) => (
              <p
                key={i}
                className="text-slate-700 leading-relaxed sm:text-base"
              >
                {sentence}
              </p>
            ))}
          </div>
        ) : (
          <p className="text-slate-700 leading-relaxed sm:text-base">
            {analysis}
          </p>
        )}
      </motion.div>
    </motion.div>
  )
}
