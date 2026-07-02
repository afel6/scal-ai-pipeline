import '@testing-library/jest-dom';

/**
 * localStorage polyfill for the jsdom/vitest environment.
 *
 * This jsdom build does not expose a usable `localStorage` (its origin is
 * opaque under the default `about:blank` document), so `globalThis.localStorage`
 * is `undefined`. App.jsx reads `localStorage.getItem('prc_user')` inside a
 * useState initializer at first render, which would throw
 * `TypeError: Cannot read properties of undefined (reading 'getItem')`.
 *
 * We install a minimal in-memory Storage shim so the production code can run
 * unmodified. Scoped to test infra only — production relies on the real
 * browser Storage.
 */
if (typeof globalThis.localStorage === 'undefined') {
  class MemoryStorage implements Storage {
    private store = new Map<string, string>();

    get length(): number {
      return this.store.size;
    }
    clear(): void {
      this.store.clear();
    }
    getItem(key: string): string | null {
      return this.store.has(key) ? this.store.get(key)! : null;
    }
    key(index: number): string | null {
      return Array.from(this.store.keys())[index] ?? null;
    }
    removeItem(key: string): void {
      this.store.delete(key);
    }
    setItem(key: string, value: string): void {
      this.store.set(key, String(value));
    }
  }

  const storage = new MemoryStorage();
  Object.defineProperty(globalThis, 'localStorage', {
    value: storage,
    configurable: true,
    writable: true,
  });
  // Keep window.localStorage pointed at the same instance when a window exists.
  if (typeof window !== 'undefined') {
    Object.defineProperty(window, 'localStorage', {
      value: storage,
      configurable: true,
      writable: true,
    });
  }
}
