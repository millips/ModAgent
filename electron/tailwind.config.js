/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{js,jsx,html}'],
  theme: {
    extend: {
      colors: {
        cyber: {
          cyan: '#00d4ff',
          blue: '#1f6feb',
          purple: '#a371f7',
          green: '#3fb950',
          red: '#f85149',
          yellow: '#d2991d',
          orange: '#db6d28',
        },
        surface: {
          900: '#0d1117',
          800: '#161b22',
          700: '#21262d',
          600: '#30363d',
          500: '#484f58',
        },
      },
      fontFamily: {
        mono: ['Cascadia Code', 'Fira Code', 'Consolas', 'monospace'],
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Microsoft YaHei"', '"PingFang SC"', 'sans-serif'],
      },
      borderRadius: {
        md: '8px',
        lg: '12px',
      },
      animation: {
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'pulse-glow': 'pulseGlow 2s infinite',
      },
      keyframes: {
        fadeIn: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        slideUp: { '0%': { opacity: '0', transform: 'translateY(8px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        pulseGlow: { '0%,100%': { boxShadow: '0 0 8px rgba(0,212,255,0.3)' }, '50%': { boxShadow: '0 0 20px rgba(0,212,255,0.6)' } },
      },
    },
  },
  plugins: [],
}
