import { motion } from 'framer-motion'

export function GlobalLoader() {
  return (
    <motion.div
      className="mt-10 flex flex-col items-center justify-center gap-4 rounded-2xl bg-white/80 py-12 shadow-sm"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
    >
      <motion.div
        className="h-12 w-12 rounded-full border-4 border-indigo-200 border-t-indigo-600"
        animate={{ rotate: 360 }}
        transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
      />
      <p className="text-slate-600">Анализируем сайт...</p>
    </motion.div>
  )
}
