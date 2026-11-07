import { Route, Routes } from 'react-router-dom';
import { Shell } from './components/Shell.jsx';
import Settings from './pages/Settings.jsx';
import Bridge from './pages/Bridge.jsx';
import Plan from './pages/Plan.jsx';
import Decisions from './pages/Decisions.jsx';
import Journal from './pages/Journal.jsx';
import Research from './pages/Research.jsx';
import ResearchSources from './pages/ResearchSources.jsx';
import Watchlist from './pages/Watchlist.jsx';
import ResearchCalendar from './pages/ResearchCalendar.jsx';
import { ConsoleProvider } from './research/Console.jsx';
import Compare from './pages/Compare.jsx';
import Risk from './pages/Risk.jsx';
import Boards from './pages/Boards.jsx';
import { LAB_TABS } from './lib/lab.js';
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
      <ConsoleProvider>
        <SymbolProvider>
          <Routes>
            <Route element={<Shell />}>
              <Route index element={<Bridge />} />
              <Route path="research" element={<Research />} />
              <Route path="research/sources" element={<ResearchSources />} />
              <Route path="research/watchlist" element={<Watchlist />} />
              <Route path="research/calendar" element={<ResearchCalendar />} />
              <Route path="research/*" element={<NotFound />} />
              <Route path="decisions" element={<Decisions />} />
              <Route path="decisions/journal" element={<Journal />} />
              <Route
                path="decisions/flight"
                element={
                  <Soon
                    area="decisions"
                    phase="10"
                    title="Flight record"
                    kicker="Decisions · Flight record"
                    lands="Scores for every desk against the plan, calibration and the desk record table land here."
                    foot={<Subtabs label="Decisions views" tabs={DECISION_TABS} />}
                  />
                }
              />
              <Route path="decisions/*" element={<NotFound />} />
              <Route path="plan/*" element={<Plan />} />
              <Route path="lab" element={<Compare />} />
              <Route path="lab/risk" element={<Risk />} />
              <Route
                path="lab/patterns"
                element={
                  <Soon
                    area="lab"
                    phase="10"
                    title="Patterns"
                    kicker="Lab · Patterns"
                    lands="Market context, your own buys scored by setup, drawdown base rates, correlation shifts and seasonality land here."
                    foot={<Subtabs label="Lab views" tabs={LAB_TABS} />}
                  />
                }
              />
              <Route path="lab/boards" element={<Boards />} />
              <Route path="lab/*" element={<NotFound />} />
              <Route path="settings" element={<Settings />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </SymbolProvider>
      </ConsoleProvider>
    </LiveProvider>
  );
}
