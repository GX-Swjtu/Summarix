import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

type StorageValues = Record<string, unknown>;

const storageValues: StorageValues = {};

function cloneValue<T>(value: T): T {
  return value === undefined ? value : structuredClone(value);
}

async function getStorageValue(keys?: string | string[] | Record<string, unknown> | null): Promise<Record<string, unknown>> {
  if (keys == null) {
    return Object.fromEntries(Object.entries(storageValues).map(([key, value]) => [key, cloneValue(value)]));
  }

  if (typeof keys === "string") {
    return keys in storageValues ? { [keys]: cloneValue(storageValues[keys]) } : {};
  }

  if (Array.isArray(keys)) {
    return Object.fromEntries(keys.filter((key) => key in storageValues).map((key) => [key, cloneValue(storageValues[key])]));
  }

  return Object.fromEntries(
    Object.entries(keys).map(([key, fallbackValue]) => [key, key in storageValues ? cloneValue(storageValues[key]) : fallbackValue])
  );
}

async function setStorageValue(items: Record<string, unknown>): Promise<void> {
  Object.assign(storageValues, items);
}

async function removeStorageValue(keys: string | string[]): Promise<void> {
  for (const key of Array.isArray(keys) ? keys : [keys]) {
    delete storageValues[key];
  }
}

beforeEach(() => {
  for (const key of Object.keys(storageValues)) {
    delete storageValues[key];
  }

  vi.stubGlobal("chrome", {
    storage: {
      local: {
        get: vi.fn(getStorageValue),
        set: vi.fn(setStorageValue),
        remove: vi.fn(removeStorageValue)
      }
    }
  });

  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn()
    }))
  });

  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    writable: true,
    value: vi.fn()
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});