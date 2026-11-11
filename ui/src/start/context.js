import { createContext, useContext } from 'react';
import { gapOf, startView } from '../lib/start.js';

export const StartContext = createContext({ view: startView(null), readiness: {}, known: false, begin: () => {}, busy: false, error: null, justDone: false, dismiss: () => {}, hide: () => {}, hidden: false, refresh: () => {}, reloadSetup: () => {}, setup: null, epoch: 0, memory: null, recheck: () => {} });

export const useStart = () => useContext(StartContext);

export function useGap(key) {
  const { readiness } = useContext(StartContext);
  return gapOf(readiness, key);
}
