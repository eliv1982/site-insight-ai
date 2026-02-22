import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import { AnalysisForm } from './components/AnalysisForm'
import { AnalysisResults } from './components/AnalysisResults'
import { GlobalLoader } from './components/GlobalLoader'
import { ErrorMessage } from './components/ErrorMessage'

const apiBase = import.meta.env.VITE_API_URL || '/api'

export default function App() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const handleSubmit = async (urlInput) => {
    const url = (urlInput || '').trim()
    if (!url) return
    setError(null)
    setResult(null)
    setLoading(true)
    const normalized = /^https?:\/\//i.test(url) ? url : `https://${url}`
    try {
      const { data } = await axios.post(
        `${apiBase}/llm/analyze-site`,
        { url: normalized },
        { timeout: 300000 }
      )
      setResult(data)
    } catch (err) {
      const message = err.response?.data?.detail ?? err.message ?? 'Произошла ошибка'
      setError(Array.isArray(message) ? message.join(', ') : message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-slate-100/80 text-slate-900">
      <div className="mx-auto max-w-content px-4 py-8 sm:px-6 sm:py-12">
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-center sm:text-left"
        >
          <h1 className="text-3xl font-bold tracking-tight text-slate-800 sm:text-4xl md:text-5xl">
            Анализатор сайтов
          </h1>
          <p className="mt-3 text-slate-600 text-base sm:text-lg">
            Получите краткое резюме содержания сайта
          </p>
        </motion.div>

        <AnalysisForm onSubmit={handleSubmit} disabled={loading} />

        <AnimatePresence mode="wait">
          {loading && <GlobalLoader key="loader" />}
          {error && (
            <ErrorMessage key="error" message={error} onDismiss={() => setError(null)} />
          )}
          {result?.final_analysis && !loading && (
            <AnalysisResults key="results" data={result.final_analysis} />
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
