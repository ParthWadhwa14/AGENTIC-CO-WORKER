import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "#d9e2ec",
        muted: "#62748a"
      }
    }
  },
  plugins: []
};

export default config;
