/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./node_modules/@steff-sson/automation-themes/templates/**/*.html",
  ],
  safelist: [
    // Step-Indicator dynamische Klassen
    "text-success",
    "text-accent",
    "text-text-muted",
    "bg-success/20",
    "bg-accent/20",
    "bg-surface-light",
    "font-medium",
    "cursor-pointer",
  ],
};
