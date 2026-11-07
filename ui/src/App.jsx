import { Route, Routes } from 'react-router-dom';
import { Shell } from './components/Shell.jsx';
import Settings from './pages/Settings.jsx';
import Bridge from './pages/Bridge.jsx';
import Plan from './pages/Plan.jsx';
import { LiveProvider } from './live/LiveProvider.jsx';
import { SymbolProvider } from './live/SymbolProvider.jsx';
import Soon from './pages/Soon.jsx';
import NotFound from './pages/NotFound.jsx';
import { useTitle } from './lib/useTitle.js';

export default function App() {
  useTitle();
  return (
    <LiveProvider>
      <SymbolProvider>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<Bridge />} />
            <Route path="research/*" element={<Soon area="research" />} />
            <Route path="decisions/*" element={<Soon area="decisions" />} />
            <Route path="plan/*" element={<Plan />} />
            <Route path="lab/*" element={<Soon area="lab" />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </SymbolProvider>
    </LiveProvider>
  );
}
