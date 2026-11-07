import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
  document.documentElement.classList.remove('dark');
  try {
    window.localStorage.clear();
  } catch {
    return;
  }
});
