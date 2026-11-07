import { createContext, useContext } from 'react';

export const ConsoleContext = createContext({ openConsole: () => {} });

export const useConsole = () => useContext(ConsoleContext);
