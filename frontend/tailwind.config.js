/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef4ff',
          100: '#dce7fd',
          500: '#3b6cf0',
          600: '#2f56d1',
          700: '#27439f',
          900: '#16245c',
        },
      },
    },
  },
  plugins: [],
};
