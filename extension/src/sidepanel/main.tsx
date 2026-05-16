import React from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles.css";
import { applyThemePreference, readCachedThemePreference } from "../shared/theme";

async function bootstrap() {
  const initialThemePreference = await readCachedThemePreference();
  applyThemePreference(initialThemePreference);

  createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App initialThemePreference={initialThemePreference} />
    </React.StrictMode>
  );
}

void bootstrap();
