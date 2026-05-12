import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#16201d",
        moss: "#3f6f5b",
        clay: "#b85636",
        paper: "#f7f3eb",
        line: "#ded7ca"
      }
    }
  },
  plugins: []
};

export default config;
