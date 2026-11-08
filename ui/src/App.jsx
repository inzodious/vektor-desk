import { Route, Routes } from 'react-router-dom';
import { Shell } from './components/Shell.jsx';
import Settings from './pages/Settings.jsx';
import FirstRun from './pages/FirstRun.jsx';
import Mixes from './pages/Mixes.jsx';
import RiskCheck from './pages/RiskCheck.jsx';
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
import Flight from './pages/Flight.jsx';
import Patterns from './pages/Patterns.jsx';
import Strategies from './pages/Strategies.jsx';
import Strategy from './pages/Strategy.jsx';
import { LiveProvider } from './live/LiveProvider.jsx';
import { SymbolProvider } from './live/SymbolProvider.jsx';
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
              <Route path="decisions/flight" element={<Flight />} />
              <Route path="decisions/*" element={<NotFound />} />
              <Route path="plan/*" element={<Plan />} />
              <Route path="lab" element={<Compare />} />
              <Route path="lab/risk" element={<Risk />} />
              <Route path="lab/mixes" element={<Mixes />} />
              <Route path="lab/strategies" element={<Strategies />} />
              <Route path="lab/strategies/:id" element={<Strategy />} />
              <Route path="lab/patterns" element={<Patterns />} />
              <Route path="lab/boards" element={<Boards />} />
              <Route path="lab/*" element={<NotFound />} />
              <Route path="settings" element={<Settings />} />
              <Route path="settings/first-run" element={<FirstRun />} />
              <Route path="start" element={<FirstRun />} />
              <Route path="settings/risk" element={<RiskCheck />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </SymbolProvider>
      </ConsoleProvider>
    </LiveProvider>
  );
}
