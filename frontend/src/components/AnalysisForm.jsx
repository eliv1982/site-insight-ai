import { useState } from 'react'
import { motion } from 'framer-motion'

export function AnalysisForm({ onSubmit, disabled }) {
  const [url, setUrl] = useState('')

  const handleSubmit = (e) => {
    e.preventDefault()
    const trimmed = url.trim()
    if (trimmed) onSubmit(trimmed)
  }

  return (
    <motion.form
      className="mt-8 sm:mt-10"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2, duration: 0.4 }}
      onSubmit={handleSubmit}
    >
      <label className="mb-2 block text-sm font-medium text-slate-600">
        Введите URL публичной веб-страницы
      </label>
      <div className="flex flex-col gap-3 sm:flex-row sm:gap-4">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com"
          className="flex-1 rounded-xl border border-slate-200 bg-white px-4 py-3.5 text-slate-900 shadow-sm transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          disabled={disabled}
          aria-label="URL публичной веб-страницы"
        />
        <button
          type="submit"
          disabled={disabled || !url.trim()}
          className="shrink-0 rounded-xl bg-indigo-600 px-6 py-3.5 font-medium text-white shadow-md transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Анализировать страницу
        </button>
      </div>
    </motion.form>
  )
}
