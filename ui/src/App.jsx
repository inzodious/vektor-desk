import { Route, Routes } from 'react-router-dom';
import { Shell } from './components/Shell.jsx';
import Settings from './pages/Settings.jsx';
import Soon from './pages/Soon.jsx';
import NotFound from './pages/NotFound.jsx';
import { useTitle } from './lib/useTitle.js';

export default function App() {
  useTitle();
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Soon area="bridge" />} />
        <Route path="research/*" element={<Soon area="research" />} />
        <Route path="decisions/*" element={<Soon area="decisions" />} />
        <Route path="plan/*" element={<Soon area="plan" />} />
        <Route path="lab/*" element={<Soon area="lab" />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
