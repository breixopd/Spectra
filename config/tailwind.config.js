/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./services/api/templates/**/*.html",
    "./services/api/static/js/**/*.js",
  ],
  safelist: [
    'md:flex-row', 'md:flex-col', 'lg:flex-row', 'sm:flex-row',
    'lg:grid-cols-2', 'lg:grid-cols-4', 'lg:grid-cols-6', 'md:grid-cols-2', 'md:grid-cols-4',
    'md:w-1/3', 'md:w-2/3', 'lg:w-1/2', 'md:w-1/2',
    'hidden', 'md:hidden', 'lg:hidden', 'sm:hidden', 'lg:flex', 'md:flex', 'sm:flex',
    'md:overflow-hidden', 'md:min-h-0', 'md:p-6', 'md:px-6', 'md:py-4',
  ],
  theme: {
    extend: {
      colors: {
        slate: { 950: '#020617' },
        emerald: { 400: '#34d399', 500: '#10b981' },
        violet: { 400: '#a78bfa', 500: '#8b5cf6' },
        rose: { 400: '#fb7185', 500: '#f43f5e' },
        amber: { 400: '#fbbf24', 500: '#f59e0b' },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'monospace'],
        sans: ['Inter', 'sans-serif'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
}
