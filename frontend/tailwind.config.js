/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    extend: {
      colors: {
        sidebar: '#141414',
        'sidebar-hover': '#1f1f1f',
        gold: '#c9a962',
        'gold-dark': '#a88b4a',
        cream: '#f7f3eb',
        'cream-dark': '#ebe4d6',
      },
      fontFamily: {
        serif: ['"Noto Serif SC"', 'Georgia', 'serif'],
        sans: ['"PingFang SC"', '"Microsoft YaHei"', 'sans-serif'],
      },
      boxShadow: {
        card: '0 2px 12px rgba(0,0,0,0.06)',
      },
    },
  },
  plugins: [],
}
