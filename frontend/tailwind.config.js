/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        dark: {
          bg: '#0F111A',
          card: '#1A1D27',
          border: '#2A2E3D',
          text: '#A0AEC0',
          accent: '#3182CE'
        },
        signal: {
          win: '#38A169',
          loss: '#E53E3E',
          pre: '#D69E2E',
          neutral: '#718096'
        }
      }
    },
  },
  plugins: [],
};
