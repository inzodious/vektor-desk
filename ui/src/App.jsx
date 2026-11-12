import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { Shell } from './components/Shell.jsx';
import Settings from './pages/Settings.jsx';
import FirstRun from './pages/FirstRun.jsx';
import Mixes from './pages/Mixes.jsx';
import RiskCheck from './pages/RiskCheck.jsx';
import Bridge from './pages/Bridge.jsx';
import Holdings from './pages/Holdings.jsx';
import Tax from './pages/Tax.jsx';
import StockPlans from './pages/StockPlans.jsx';
import Results from './pages/Results.jsx';
import Decisions from './pages/Decisions.jsx';
import Journal from './pages/Journal.jsx';
import Research from './pages/Research.jsx';
import Opportunities from './pages/Opportunities.jsx';
import ResearchSources from './pages/ResearchSources.jsx';
import Watchlist from './pages/Watchlist.jsx';
import ResearchCalendar from './pages/ResearchCalendar.jsx';
import { ConsoleProvider } from './research/Console.jsx';
import Compare from './pages/Compare.jsx';
import Risk from './pages/Risk.jsx';
import Boards from './pages/Boards.jsx';
import Flight from './pages/Flight.jsx';
import Patterns from './pages/Patterns.jsx';
import Replay from './pages/Replay.jsx';
import Strategies from './pages/Strategies.jsx';
import Strategy from './pages/Strategy.jsx';
import { LiveProvider } from './live/LiveProvider.jsx';
import { SymbolProvider } from './live/SymbolProvider.jsx';
import { StartProvider } from './start/StartProvider.jsx';
import { AsOfProvider } from './asof/AsOfProvider.jsx';
import NotFound from './pages/NotFound.jsx';
import { movedPath } from './lib/areas.js';
import { useTitle } from './lib/useTitle.js';

// ---------- old links ----------
function Moved() {
  const { pathname, search, hash } = useLocation();
  const to = movedPath(pathname, search);
  return to ? <Navigate to={`${to}${search}${hash}`} replace /> : <NotFound />;
}

export default function App() {
  useTitle();
  return (
    <LiveProvider>
      <ConsoleProvider>
        <SymbolProvider>
          <StartProvider>
            <AsOfProvider>
            <Routes>
              <Route element={<Shell />}>
                <Route index element={<Bridge />} />
                <Route path="results" element={<Navigate to="/results/day" replace />} />
                <Route path="results/:kind" element={<Results />} />
                <Route path="portfolio" element={<Holdings />} />
                <Route path="portfolio/stocks" element={<StockPlans />} />
                <Route path="portfolio/risk" element={<Risk />} />
                <Route path="portfolio/tax" element={<Tax />} />
                <Route path="portfolio/*" element={<NotFound />} />
                <Route path="strategies" element={<Strategies />} />
                <Route path="strategies/mixes" element={<Mixes />} />
                <Route path="strategies/habits" element={<Patterns />} />
                <Route path="strategies/habits/replay" element={<Replay />} />
                <Route path="strategies/:id" element={<Strategy />} />
                <Route path="strategies/*" element={<NotFound />} />
                <Route path="decisions" element={<Decisions />} />
                <Route path="decisions/journal" element={<Journal />} />
                <Route path="decisions/flight" element={<Flight />} />
                <Route path="decisions/*" element={<NotFound />} />
                <Route path="research" element={<Research />} />
                <Route path="research/opportunities" element={<Opportunities />} />
                <Route path="research/sources" element={<ResearchSources />} />
                <Route path="research/watchlist" element={<Watchlist />} />
                <Route path="research/calendar" element={<ResearchCalendar />} />
                <Route path="research/compare" element={<Compare />} />
                <Route path="research/boards" element={<Boards />} />
                <Route path="research/*" element={<NotFound />} />
                <Route path="settings" element={<Settings tab="desk" />} />
                <Route path="settings/crew" element={<Settings tab="crew" />} />
                <Route path="settings/data" element={<Settings tab="data" />} />
                <Route path="settings/box" element={<Settings tab="box" />} />
                <Route path="settings/risk" element={<RiskCheck />} />
                <Route path="settings/first-run" element={<FirstRun />} />
                <Route path="start" element={<FirstRun />} />
                <Route path="plan/*" element={<Moved />} />
                <Route path="lab/*" element={<Moved />} />
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
            </AsOfProvider>
          </StartProvider>
        </SymbolProvider>
      </ConsoleProvider>
    </LiveProvider>
  );
}
