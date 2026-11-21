// Saturday Multiverse — procedural character portraits (original SVG art).
// Same seed + palette always yields the same face: deterministic, data-only.

const PALETTES = {
  violet: { rim: "#9b8cff", deep: "#2a1b4a", mid: "#4a3a7a", mark: "#43e8d8" },
  iron:   { rim: "#8fa3b8", deep: "#1c2430", mid: "#39495c", mark: "#e8b46b" },
  brass:  { rim: "#e8b46b", deep: "#2d2410", mid: "#5c4a26", mark: "#43e8d8" },
  ember:  { rim: "#ff9d5c", deep: "#2d1a10", mid: "#5c3a26", mark: "#9b8cff" },
  tide:   { rim: "#43e8d8", deep: "#10262a", mid: "#1e4a50", mark: "#e8b46b" },
};

// tiny deterministic hash → PRNG
function rngFrom(seed) {
  let h = 2166136261 >>> 0;
  for (const ch of String(seed)) {
    h ^= ch.codePointAt(0);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return function next() {
    h ^= h << 13; h >>>= 0;
    h ^= h >> 17;
    h ^= h << 5; h >>>= 0;
    return (h % 100000) / 100000;
  };
}

export function portraitSVG(seed, paletteName = "tide", archetype = "") {
  const p = PALETTES[paletteName] || PALETTES.tide;
  const rand = rngFrom(`${seed}|${paletteName}|${archetype}`);
  const jawW = 30 + rand() * 8;          // half-width of jaw
  const eyeY = 38 + rand() * 6;
  const eyeDX = 9 + rand() * 4;
  const eyeR = 2.6 + rand() * 1.6;
  const browTilt = (rand() - 0.5) * 6;
  const mouthW = 9 + rand() * 7;
  const mouthY = 56 + rand() * 5;
  const hairStyle = Math.floor(rand() * 4);
  const markKind = Math.floor(rand() * 3);

  let hair = "";
  if (hairStyle === 0) {
    hair = `<path d="M28 40 Q36 16 64 18 Q92 20 92 42 Q84 28 64 28 Q44 28 28 40Z" fill="${p.deep}"/>`;
  } else if (hairStyle === 1) {
    hair = `<path d="M26 46 Q30 14 64 14 Q98 16 96 48 Q90 34 74 30 Q56 26 40 34 Q30 38 26 46Z" fill="${p.deep}"/>
            <path d="M30 34 Q40 18 62 18" stroke="${p.rim}" stroke-width="1" fill="none" opacity="0.6"/>`;
  } else if (hairStyle === 2) {
    hair = `<path d="M30 44 L26 18 L44 30 L58 14 L74 28 L94 20 L90 44 Q76 30 62 30 Q46 30 30 44Z" fill="${p.deep}"/>`;
  } else {
    hair = `<ellipse cx="64" cy="24" rx="34" ry="14" fill="${p.deep}"/>`;
  }

  let mark = "";
  const mx = 64, my = 47 + rand() * 4;
  if (markKind === 0) {
    mark = `<circle cx="${mx}" cy="${my}" r="3.2" fill="none" stroke="${p.mark}" stroke-width="1.1" opacity="0.9"/>
            <circle cx="${mx}" cy="${my}" r="6.4" fill="none" stroke="${p.mark}" stroke-width="0.7" opacity="0.5"/>`;
  } else if (markKind === 1) {
    mark = `<path d="M${mx - 5} ${my} L${mx} ${my - 5} L${mx + 5} ${my} L${mx} ${my + 5}Z" fill="none" stroke="${p.mark}" stroke-width="1.1" opacity="0.9"/>`;
  } else {
    mark = `<path d="M${mx - 6} ${my} Q${mx} ${my - 7} ${mx + 6} ${my} Q${mx} ${my + 3} ${mx - 6} ${my}Z" fill="none" stroke="${p.mark}" stroke-width="1.1" opacity="0.9"/>`;
  }

  return `<svg viewBox="0 0 128 128" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="portrait">
  <defs>
    <radialGradient id="pg-${paletteName}" cx="50%" cy="36%" r="75%">
      <stop offset="0%" stop-color="${p.mid}"/>
      <stop offset="100%" stop-color="${p.deep}"/>
    </radialGradient>
  </defs>
  <rect width="128" height="128" fill="url(#pg-${paletteName})"/>
  <circle cx="64" cy="66" r="52" fill="none" stroke="${p.rim}" stroke-width="1" opacity="0.35"/>
  ${hair}
  <path d="M${64 - jawW} 44 Q${64 - jawW - 2} 74 ${64 - jawW / 2} 88 Q64 100 ${64 + jawW / 2} 88 Q${64 + jawW + 2} 74 ${64 + jawW} 44 Q64 34 ${64 - jawW} 44Z"
        fill="${p.mid}" stroke="${p.rim}" stroke-width="1.4" opacity="0.95"/>
  <circle cx="${64 - eyeDX}" cy="${eyeY}" r="${eyeR}" fill="${p.rim}"/>
  <circle cx="${64 + eyeDX}" cy="${eyeY}" r="${eyeR}" fill="${p.rim}"/>
  <path d="M${64 - eyeDX - 5} ${eyeY - 6} L${64 - eyeDX + 4} ${eyeY - 6 + browTilt}" stroke="${p.deep}" stroke-width="2" fill="none"/>
  <path d="M${64 + eyeDX - 4} ${eyeY - 6 + browTilt} L${64 + eyeDX + 5} ${eyeY - 6}" stroke="${p.deep}" stroke-width="2" fill="none"/>
  <path d="M${64 - mouthW / 2} ${mouthY} Q64 ${mouthY + 3 + rand() * 3} ${64 + mouthW / 2} ${mouthY}" stroke="${p.deep}" stroke-width="1.6" fill="none"/>
  ${mark}
  <path d="M20 128 Q30 96 64 94 Q98 96 108 128Z" fill="${p.deep}" opacity="0.85"/>
</svg>`;
}
