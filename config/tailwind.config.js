const path = require('path');

/** @type {import('tailwindcss').Config} */
module.exports = {
  // Paths must be relative to this file (config/), not the repo root — Docker builds from cd config.
  content: [
    path.join(__dirname, '../services/api/templates/**/*.html'),
    path.join(__dirname, '../services/api/static/js/**/*.js'),
  ],
  safelist: [{ pattern: /^animate-/ }],
  theme: {
    extend: {
      colors: {
        slate: { 950: '#020617' },
        emerald: { 400: '#34d399', 500: '#10b981', 600: '#059669' },
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
};
