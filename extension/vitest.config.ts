import { defineConfig } from "vitest/config";

export default defineConfig({
  define: {
    __SUMMARIX_DEFAULT_API_BASE__: JSON.stringify("https://compiled.example.com")
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true
  }
});