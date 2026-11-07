import { Route, Routes } from 'react-router-dom';
import { Shell } from './components/Shell.jsx';
import Settings from './pages/Settings.jsx';
import Bridge from './pages/Bridge.jsx';
import Plan from './pages/Plan.jsx';
import Decisions from './pages/Decisions.jsx';
import Journal from './pages/Journal.jsx';
import { Subtabs } from './components/Subtabs.jsx';
import { DECISION_TABS } from './lib/decisions.js';
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
            <Route path="decisions" element={<Decisions />} />
            <Route path="decisions/journal" element={<Journal />} />
            <Route path="decisions/flight" element={<Soon area="decisions" phase="10" title="Flight record" kicker="Decisions · Flight record" lands="Scores for every desk against the plan, calibration and the desk record table land here." foot={<Subtabs label="Decisions views" tabs={DECISION_TABS} />} />} />
            <Route path="decisions/*" element={<NotFound />} />
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
