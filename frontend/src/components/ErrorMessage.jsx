import { motion } from 'framer-motion'

export function ErrorMessage({ message, onDismiss }) {
  return (
    <motion.div
      className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      role="alert"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="flex-1 text-sm sm:text-base">{message}</p>
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 rounded-lg px-2 py-1 text-red-600 hover:bg-red-100"
          aria-label="Закрыть"
        >
          ✕
        </button>
      </div>
    </motion.div>
  )
}
