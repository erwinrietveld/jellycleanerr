/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './static/index.html',
    './static/app.js',
  ],
  theme: {
    extend: {
      colors: {
        jellybg: '#0d1117',
        jellycard: '#111827',
        jellyline: '#374151',
      },
    },
  },
};
