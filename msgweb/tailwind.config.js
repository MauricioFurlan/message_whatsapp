/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./static/index.html"],
  safelist: [
    // Cores de fundo das linhas inválidas na tabela (geradas dinamicamente via JS)
    'bg-rose-50',    'hover:bg-rose-100',
    'bg-orange-50',  'hover:bg-orange-100',
    'bg-amber-50',   'hover:bg-amber-100',
    'bg-yellow-50',  'hover:bg-yellow-100',
    'bg-red-50',     'hover:bg-red-100',
    'bg-pink-50',    'hover:bg-pink-100',
    'bg-fuchsia-50', 'hover:bg-fuchsia-100',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
