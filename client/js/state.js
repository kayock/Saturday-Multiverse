// Saturday Multiverse — minimal reactive store
const listeners = new Set();

export const state = {
  view: null,          // campaign view from server
  campaigns: [],       // saved campaigns list
  packs: [],
  busy: false,
  ui: { panel: null },
};

export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }

export function emit() { for (const fn of listeners) fn(state); }

export function setView(view) { state.view = view; emit(); }
