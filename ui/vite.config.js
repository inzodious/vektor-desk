import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { configDefaults } from 'vitest/config';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const FIXTURES = fileURLToPath(new URL('./src/fixtures/', import.meta.url));

function fixtureApi() {
  const serve = (req, res, next) => {
    const url = new URL(req.url, 'http://desk');
    if (!url.pathname.startsWith('/api/')) return next();
    const scenario = req.headers['x-desk-scenario'] || url.searchParams.get('scenario') || '';
    const base = url.pathname.slice(5).replace(/\/+$/, '').replace(/\//g, '.') || 'index';
    const file = [scenario && `${FIXTURES}${base}.${scenario}.json`, `${FIXTURES}${base}.json`].find((f) => f && existsSync(f));
    res.setHeader('Cache-Control', 'no-store');
    if (!file) {
      res.statusCode = 404;
      res.setHeader('Content-Type', 'application/json');
      return res.end(JSON.stringify({ detail: 'Not Found' }));
    }
    res.setHeader('Content-Type', 'application/json');
    res.end(readFileSync(file));
  };
  return {
    name: 'desk-fixture-api',
    configureServer(server) { server.middlewares.use(serve); },
    configurePreviewServer(server) { server.middlewares.use(serve); },
  };
}

export default defineConfig(() => {
  const fixtures = process.env.DESK_FIXTURES === '1';
  const api = process.env.DESK_API || 'http://127.0.0.1:8000';
  return {
    plugins: [react(), ...(fixtures ? [fixtureApi()] : [])],
    server: fixtures ? {} : { proxy: { '/api': api } },
    preview: fixtures ? {} : { proxy: { '/api': api } },
    build: { outDir: 'dist', emptyOutDir: true },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.js'],
      include: ['src/**/*.test.{js,jsx}'],
      exclude: [...configDefaults.exclude, 'e2e/**'],
    },
  };
});
