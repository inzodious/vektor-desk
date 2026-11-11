const ROOM = 4;
const KEEP = 2;

export function dueRows(items = [], steps = [], room = ROOM, keep = KEEP) {
  const stepRoom = Math.min(steps.length, keep);
  const queue = items.slice(0, Math.max(room - stepRoom, 0));
  const plan = steps.slice(0, Math.max(room - queue.length, 0));
  return { queue, plan, moreQueue: items.length - queue.length, moreSteps: steps.length - plan.length };
}

export function movers(symbols = [], top = 3) {
  return symbols
    .filter((r) => r.change_pct != null && Math.abs(r.day_change || 0) >= 0.5)
    .sort((a, b) => Math.abs(b.day_change) - Math.abs(a.day_change))
    .slice(0, top);
}

export function dueHead(waiting, steps) {
  if (!waiting && !steps) return 'Nothing due';
  return [waiting ? `${waiting} to decide` : null, steps ? `${steps} plan ${steps === 1 ? 'step' : 'steps'}` : null].filter(Boolean).join(' · ');
}
