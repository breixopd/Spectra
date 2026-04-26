/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "../templates/**/*.html",
    "../static/js/**/*.js",
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
