// Saturday Multiverse — SVG vignettes for interior & adventure scenes.
// Each vignette is an original layered illustration; hotspots glow and
// dispatch clicks to the game. Pure vector = crisp at every size.

const VB = 'viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg"';

const SCENES = {
  camp: `
    <defs>
      <radialGradient id="fireGlow" cx="50%" cy="78%" r="45%">
        <stop offset="0%" stop-color="#ff9d5c" stop-opacity="0.75"/>
        <stop offset="45%" stop-color="#e8b46b" stop-opacity="0.28"/>
        <stop offset="100%" stop-color="#e8b46b" stop-opacity="0"/>
      </radialGradient>
      <linearGradient id="campSky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#0a0817"/><stop offset="100%" stop-color="#241742"/>
      </linearGradient>
    </defs>
    <rect width="1600" height="900" fill="url(#campSky)"/>
    <circle cx="1280" cy="150" r="70" fill="#ded9ee" opacity="0.9"/>
    <circle cx="1255" cy="135" r="14" fill="#b9b3cf" opacity="0.5"/>
    <circle cx="1300" cy="170" r="9" fill="#b9b3cf" opacity="0.4"/>
    <ellipse cx="800" cy="640" rx="980" ry="330" fill="#171223"/>
    <path d="M0 620 Q400 560 800 610 T1600 600 L1600 900 L0 900Z" fill="#1a1430"/>
    <ellipse cx="800" cy="660" rx="420" ry="150" fill="url(#fireGlow)"/>
    <g stroke="#3c3256" stroke-width="7" fill="none" opacity="0.9">
      <path d="M300 700 Q520 660 760 690"/><path d="M840 690 Q1080 660 1300 700"/>
    </g>
    <g fill="#1e1834">
      <ellipse cx="540" cy="620" rx="26" ry="52"/><circle cx="540" cy="560" r="26"/>
    </g>
    <path d="M528 540 Q540 522 552 540" stroke="#2c2248" stroke-width="8" fill="none"/>
    <g>
      <path d="M770 660 Q800 590 830 660 Q815 645 800 652 Q785 645 770 660Z" fill="#ff9d5c" opacity="0.95"/>
      <path d="M788 660 Q800 615 812 660 Q806 650 800 654 Q794 650 788 660Z" fill="#ffecbe"/>
    </g>
    <g fill="#3c3256" opacity="0.8">
      <path d="M640 640 L700 580 L706 640Z"/><path d="M900 636 L960 576 L966 636Z"/>
    </g>
    <g opacity="0.85" stroke="#6b6584" stroke-width="2" fill="#241d3e">
      <rect x="1080" y="560" width="26" height="34"/><rect x="1120" y="548" width="26" height="46"/>
      <rect x="1160" y="566" width="26" height="28"/><rect x="1102" y="522" width="22" height="20"/>
    </g>`,
  tavern: `
    <defs>
      <radialGradient id="tavWarm" cx="50%" cy="50%" r="75%">
        <stop offset="0%" stop-color="#3a2a1c"/><stop offset="100%" stop-color="#141126"/>
      </radialGradient>
      <radialGradient id="lampG" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="#ffecbe" stop-opacity="0.9"/>
        <stop offset="100%" stop-color="#e8b46b" stop-opacity="0"/>
      </radialGradient>
    </defs>
    <rect width="1600" height="900" fill="url(#tavWarm)"/>
    <rect y="0" width="1600" height="120" fill="#100c20"/>
    <g fill="#241d3e" stroke="#3c3256" stroke-width="3">
      <rect x="180" y="180" width="300" height="120"/>
      <rect x="520" y="180" width="300" height="120"/><rect x="860" y="180" width="300" height="120"/>
    </g>
    <g stroke="#544a78" stroke-width="2" opacity="0.6">
      <line x1="330" y1="180" x2="330" y2="300"/><line x1="670" y1="180" x2="670" y2="300"/>
      <line x1="1010" y1="180" x2="1010" y2="300"/><line x1="180" y1="240" x2="1160" y2="240"/>
    </g>
    <rect x="1350" y="140" width="180" height="330" rx="10" fill="#1a142e" stroke="#3c3256" stroke-width="3"/>
    <circle cx="1440" cy="300" r="46" fill="#2c2248" stroke="#43e8d8" stroke-width="2" opacity="0.9"/>
    <circle cx="1440" cy="300" r="16" fill="#43e8d8" opacity="0.75"/>
    <rect y="600" width="1600" height="300" fill="#241a12"/>
    <rect y="570" width="1600" height="50" fill="#3a2a1c"/>
    <rect y="560" width="1600" height="18" fill="#4a3626"/>
    <g fill="#1e1834" stroke="#3c3256" stroke-width="2">
      <rect x="240" y="430" width="70" height="130" rx="8"/><rect x="340" y="450" width="70" height="110" rx="8"/>
    </g>
    <g fill="#c9b8a0" opacity="0.7">
      <rect x="1220" y="500" width="44" height="60" rx="6"/><rect x="1280" y="515" width="44" height="45" rx="6"/>
    </g>
    <g>
      <circle cx="620" cy="330" r="90" fill="url(#lampG)"/>
      <line x1="620" y1="240" x2="620" y2="300" stroke="#3c3256" stroke-width="4"/>
      <ellipse cx="620" cy="320" rx="16" ry="22" fill="#ffecbe"/>
    </g>
    <g>
      <circle cx="1050" cy="300" r="90" fill="url(#lampG)"/>
      <ellipse cx="1050" cy="316" rx="14" ry="20" fill="#ffecbe"/>
    </g>
    <g fill="#171223">
      <ellipse cx="760" cy="560" rx="90" ry="120"/>
      <circle cx="760" cy="420" r="56"/>
      <ellipse cx="735" cy="404" rx="9" ry="12" fill="#2c2248"/>
      <path d="M700 400 Q760 350 820 400 Q790 380 760 382 Q730 380 700 400Z" fill="#0d0a18"/>
    </g>
    <circle cx="742" cy="410" r="10" fill="#43e8d8" opacity="0.85"/>
    <circle cx="782" cy="410" r="10" fill="#8f86ad"/>`,
  lighthouse: `
    <defs>
      <linearGradient id="lhWall" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="#171129"/><stop offset="55%" stop-color="#2c2248"/><stop offset="100%" stop-color="#141126"/>
      </linearGradient>
    </defs>
    <rect width="1600" height="900" fill="url(#lhWall)"/>
    <g fill="none" stroke="#3c3256" stroke-width="14" opacity="0.9">
      <path d="M1150 900 Q1000 600 1080 330 Q1130 150 1060 0"/>
      <path d="M1330 900 Q1190 620 1250 340 Q1300 170 1240 0"/>
    </g>
    <g fill="#241d3e">
      <ellipse cx="1210" cy="880" rx="150" ry="26"/>
      <ellipse cx="1205" cy="700" rx="130" ry="24"/>
      <ellipse cx="1215" cy="520" rx="120" ry="22"/>
      <ellipse cx="1180" cy="350" rx="110" ry="20"/>
    </g>
    <path d="M300 120 L620 380 L620 900 L300 900Z" fill="#100c20"/>
    <rect x="360" y="420" width="200" height="300" fill="#241d3e" stroke="#3c3256" stroke-width="6"/>
    <path d="M360 420 L560 420 L520 380 L400 380Z" fill="#1a142e"/>
    <path d="M420 500 L520 500 L520 700 L420 700Z" fill="#2c2248"/>
    <circle cx="470" cy="580" r="18" fill="#3c3256"/>
    <rect x="660" y="640" width="420" height="30" rx="6" fill="#3a2a1c"/>
    <rect x="700" y="670" width="26" height="60" fill="#241d3e"/><rect x="940" y="670" width="26" height="60" fill="#241d3e"/>
    <path d="M700 636 Q760 560 830 600 Q780 620 760 636Z" fill="#c9b8a0" opacity="0.55"/>
    <g opacity="0.9">
      <path d="M640 300 Q820 240 1000 290 Q1100 320 1180 300" stroke="#9b8cff" stroke-width="6" fill="none" opacity="0.4"/>
      <path d="M640 340 Q820 290 1000 330 Q1090 355 1180 340" stroke="#9b8cff" stroke-width="3" fill="none" opacity="0.25"/>
    </g>
    <circle cx="870" cy="260" r="5" fill="#cfd0ff" opacity="0.9"/>
    <g fill="#8f86ad" opacity="0.5">
      <circle cx="500" cy="240" r="3"/><circle cx="560" cy="210" r="2.4"/><circle cx="620" cy="250" r="2"/>
    </g>`,
  seacave: `
    <defs>
      <radialGradient id="poolG" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="#43e8d8" stop-opacity="0.85"/>
        <stop offset="55%" stop-color="#2a9c94" stop-opacity="0.35"/>
        <stop offset="100%" stop-color="#43e8d8" stop-opacity="0"/>
      </radialGradient>
    </defs>
    <rect width="1600" height="900" fill="#0d0a18"/>
    <path d="M0 0 L1600 0 L1600 240 Q1400 320 1250 260 Q1100 200 980 280 Q820 380 700 300 Q560 210 420 300 Q260 400 0 300Z" fill="#171129"/>
    <g stroke="#6b6584" stroke-width="5" opacity="0.85">
      <line x1="300" y1="120" x2="300" y2="330"/><line x1="480" y1="90" x2="480" y2="300"/>
      <line x1="700" y1="140" x2="700" y2="340"/><line x1="900" y1="110" x2="900" y2="320"/>
      <line x1="1100" y1="150" x2="1100" y2="350"/><line x1="1300" y1="120" x2="1300" y2="330"/>
    </g>
    <g fill="#3c3256"><circle cx="300" cy="336" r="7"/><circle cx="480" cy="306" r="7"/><circle cx="700" cy="346" r="7"/><circle cx="900" cy="326" r="7"/><circle cx="1100" cy="356" r="7"/><circle cx="1300" cy="336" r="7"/></g>
    <path d="M0 900 L0 620 Q300 540 640 600 Q1000 660 1300 590 Q1450 560 1600 600 L1600 900Z" fill="#1a1430"/>
    <ellipse cx="800" cy="700" rx="300" ry="90" fill="#120e24"/>
    <ellipse cx="800" cy="690" rx="220" ry="60" fill="url(#poolG)"/>
    <ellipse cx="800" cy="688" rx="120" ry="30" fill="#43e8d8" opacity="0.4"/>
    <g fill="#43e8d8" opacity="0.6">
      <circle cx="700" cy="640" r="4"/><circle cx="930" cy="650" r="3.4"/><circle cx="820" cy="620" r="2.6"/>
    </g>
    <g fill="#241d3e">
      <path d="M1180 620 Q1260 560 1340 620 L1340 640 Q1260 600 1180 640Z"/>
      <ellipse cx="430" cy="640" rx="70" ry="40"/>
    </g>
    <path d="M800 420 Q810 470 800 520" stroke="#43e8d8" stroke-width="4" opacity="0.6" fill="none"/>`,
  wreck: `
    <defs>
      <linearGradient id="wreckSky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#171129"/><stop offset="100%" stop-color="#2a1c5c"/>
      </linearGradient>
    </defs>
    <rect width="1600" height="900" fill="url(#wreckSky)"/>
    <rect y="700" width="1600" height="200" fill="#171223"/>
    <path d="M0 700 Q400 660 800 690 T1600 680 L1600 900 L0 900Z" fill="#221736"/>
    <g transform="rotate(-6 800 620)">
      <path d="M240 620 Q300 760 560 780 L1240 780 Q1420 740 1500 620 Q1350 580 1200 590 L420 590 Q300 590 240 620Z" fill="#1e1834"/>
      <path d="M420 590 L1200 590 L1180 540 L440 540Z" fill="#241d3e"/>
      <g stroke="#3c3256" stroke-width="6" opacity="0.8">
        <line x1="500" y1="590" x2="500" y2="780"/><line x1="700" y1="590" x2="700" y2="780"/>
        <line x1="900" y1="590" x2="900" y2="780"/><line x1="1100" y1="590" x2="1100" y2="780"/>
      </g>
      <line x1="700" y1="540" x2="660" y2="140" stroke="#2c2248" stroke-width="14"/>
      <line x1="660" y1="200" x2="940" y2="320" stroke="#2c2248" stroke-width="6"/>
      <path d="M940 320 L900 520 L700 500Z" fill="#171129" opacity="0.9"/>
    </g>
    <g transform="translate(1240 640)">
      <path d="M-40 -70 A40 52 0 0 1 40 -70 L40 0 L-40 0Z" fill="#e8b46b"/>
      <path d="M-40 -70 A40 52 0 0 1 40 -70 L40 -52 A32 42 0 0 0 -32 -52 L-32 0 L-40 0Z" fill="#f4d398"/>
      <rect x="-12" y="-96" width="24" height="26" rx="10" fill="none" stroke="#e8b46b" stroke-width="10"/>
      <ellipse cx="0" cy="10" rx="90" ry="16" fill="#e8b46b" opacity="0.2"/>
    </g>
    <g fill="#8f86ad" opacity="0.6">
      <circle cx="380" cy="160" r="3"/><circle cx="470" cy="120" r="2.4"/><circle cx="560" cy="180" r="2"/>
    </g>`,
  saltgrave: `
    <defs>
      <linearGradient id="sgSky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#241a40"/><stop offset="55%" stop-color="#2e2148"/><stop offset="100%" stop-color="#1a1230"/>
      </linearGradient>
      <radialGradient id="lampG2" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="#ffecbe" stop-opacity="0.95"/>
        <stop offset="45%" stop-color="#e8b46b" stop-opacity="0.45"/>
        <stop offset="100%" stop-color="#e8b46b" stop-opacity="0"/>
      </radialGradient>
      <linearGradient id="sgSea" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#1a1434"/><stop offset="100%" stop-color="#0d0a20"/>
      </linearGradient>
    </defs>
    <rect width="1600" height="900" fill="url(#sgSky)"/>
    <circle cx="240" cy="130" r="58" fill="#ded9ee" opacity="0.85"/>
    <circle cx="222" cy="118" r="12" fill="#b9b3cf" opacity="0.5"/>
    <g fill="#cfd0ff" opacity="0.7">
      <circle cx="500" cy="90" r="2.5"/><circle cx="700" cy="60" r="2"/><circle cx="900" cy="110" r="2.6"/>
      <circle cx="1150" cy="70" r="2"/><circle cx="1400" cy="120" r="2.4"/><circle cx="1550" cy="60" r="2"/>
    </g>
    <rect y="470" width="1600" height="430" fill="url(#sgSea)"/>
    <path d="M0 470 L1600 470 L1600 486 Q1200 505 800 490 Q400 475 0 492Z" fill="#241a44"/>
    <g fill="#221a3e" stroke="#3c3256" stroke-width="3">
      <rect x="40" y="380" width="280" height="120"/><rect x="80" y="300" width="230" height="100"/>
      <rect x="1260" y="370" width="290" height="130"/><rect x="1300" y="290" width="220" height="105"/>
    </g>
    <g fill="none" stroke="#544a78" stroke-width="2" opacity="0.55">
      <rect x="70" y="410" width="50" height="60"/><rect x="150" y="410" width="50" height="60"/>
      <rect x="1300" y="400" width="50" height="64"/><rect x="1390" y="400" width="50" height="64"/>
    </g>
    <path d="M1010 470 L1010 210 L1150 210 L1150 470Z" fill="#2a2148" stroke="#3c3256" stroke-width="3"/>
    <rect x="990" y="188" width="180" height="28" fill="#221a3e" stroke="#3c3256" stroke-width="2"/>
    <circle cx="1080" cy="258" r="18" fill="#e8b46b" opacity="0.9"/>
    <circle cx="1080" cy="258" r="34" fill="url(#lampG2)"/>
    <rect x="1050" y="330" width="52" height="72" fill="#3c3256"/>
    <g>
      ${[0, 1, 2, 3, 4, 5, 6, 7].map((i) => {
        const x = 430 + i * 118;
        return `<circle cx="${x}" cy="420" r="46" fill="url(#lampG2)"/>
          <line x1="${x}" y1="376" x2="${x}" y2="398" stroke="#3c3256" stroke-width="4"/>
          <rect x="${x - 11}" y="398" width="22" height="30" rx="4" fill="none" stroke="#e8b46b" stroke-width="3.5"/>
          <rect x="${x - 6}" y="404" width="12" height="18" rx="3" fill="#ffecbe"/>`;
      }).join("")}
      <circle cx="1322" cy="420" r="40" fill="rgba(30,26,48,0.95)"/>
      <circle cx="1322" cy="420" r="40" fill="none" stroke="#544a78" stroke-width="2.5" stroke-dasharray="5 7"/>
    </g>
    <g opacity="0.4" stroke="#9b8cff" stroke-width="2.5" fill="none">
      <path d="M120 640 Q400 680 700 645 T1300 650 T1600 640"/>
    </g>
    <g opacity="0.28" stroke="#8f86ad" stroke-width="2" fill="none">
      <path d="M0 560 Q300 580 600 565 T1200 570 T1600 560"/>
    </g>`,
  umbral: `
    <defs>
      <linearGradient id="umSky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#1a0f18"/><stop offset="60%" stop-color="#2d1226"/><stop offset="100%" stop-color="#140b1c"/>
      </linearGradient>
    </defs>
    <rect width="1600" height="900" fill="url(#umSky)"/>
    <g fill="#ff9d5c" opacity="0.8">
      ${Array.from({ length: 40 }, (_, i) => {
        const x = (i * 173) % 1600; const y = ((i * 97) % 380) + 40;
        const r = 1.5 + (i % 3);
        return `<circle cx="${x}" cy="${y}" r="${r}" opacity="${0.3 + (i % 5) * 0.14}"/>`;
      }).join("")}
    </g>
    <path d="M0 640 Q300 560 640 620 Q980 680 1300 590 Q1450 550 1600 600 L1600 900 L0 900Z" fill="#171020"/>
    <path d="M0 720 Q400 660 800 700 T1600 690 L1600 900 L0 900Z" fill="#100a16"/>
    <g fill="#241d3e" stroke="#3c3256" stroke-width="6">
      <path d="M300 700 L340 540 L380 700Z"/><path d="M330 560 L360 480 L392 560Z"/>
    </g>
    <circle cx="360" cy="500" r="8" fill="#43e8d8" opacity="0.8"/>
    <g fill="#241d3e" stroke="#3c3256" stroke-width="6"><path d="M1250 690 L1280 560 L1310 690Z"/></g>
    <circle cx="1280" cy="585" r="8" fill="#e8b46b" opacity="0.8"/>
    <g>
      <ellipse cx="800" cy="640" rx="330" ry="26" fill="#ff9d5c" opacity="0.10"/>
      ${[0, 1, 2, 3, 4, 5].map((i) => `<circle cx="${620 + i * 72}" cy="${630 - (i % 2) * 14}" r="7" fill="${i % 2 ? "#e8b46b" : "#ff9d5c"}" opacity="${0.85 - (i % 3) * 0.2}"/>`).join("")}
    </g>
    <g fill="#1c1428" opacity="0.9">
      <ellipse cx="760" cy="600" rx="26" ry="70"/><circle cx="760" cy="516" r="24"/>
    </g>`,
  tidegate: `
    <defs>
      <linearGradient id="tgSky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#0a0817"/><stop offset="60%" stop-color="#1a1030"/><stop offset="100%" stop-color="#241742"/>
      </linearGradient>
    </defs>
    <rect width="1600" height="900" fill="url(#tgSky)"/>
    <rect y="520" width="1600" height="380" fill="#120e24"/>
    <rect x="600" y="80" width="400" height="26" fill="rgba(155,140,255,0.25)"/>
    <rect x="520" y="140" width="560" height="20" fill="rgba(155,140,255,0.16)"/>
    <g fill="#1e1834" stroke="#3c3256" stroke-width="4">
      <rect x="380" y="600" width="18" height="90"/><rect x="330" y="590" width="120" height="26" rx="4"/>
    </g>`,
};

export function vignetteFor(view) {
  const beat = view?.scene?.beat;
  const locId = view?.location?.id;
  if (beat && beat.startsWith("sg_")) return "saltgrave";
  return SCENES[locId] ? locId : "tidegate";
}

export function renderVignette(el, view, onHotspot) {
  const key = vignetteFor(view);
  const base = `<svg ${VB}>${SCENES[key] || SCENES.tidegate}</svg>`;
  const hotspots = view?.scene?.hotspots || [];
  const markers = hotspots.map((h) => `
    <g class="hs-marker" data-hotspot="${h.id}" style="cursor:pointer">
      <circle cx="${(h.x / 100) * 1600}" cy="${(h.y / 100) * 900}" r="26" fill="rgba(155,140,255,0.12)" stroke="rgba(233,228,242,0.7)" stroke-dasharray="4 5" stroke-width="2">
        <animate attributeName="r" values="20;30;20" dur="3s" repeatCount="indefinite"/>
        <animate attributeName="opacity" values="0.9;0.5;0.9" dur="3s" repeatCount="indefinite"/>
      </circle>
      <circle cx="${(h.x / 100) * 1600}" cy="${(h.y / 100) * 900}" r="6" fill="#cfd0ff"/>
      <text x="${(h.x / 100) * 1600}" y="${(h.y / 100) * 900 - 38}" text-anchor="middle" font-size="24" fill="#e9e4f2" opacity="0.85" font-family="serif" font-style="italic">${escapeHtml(h.label)}</text>
    </g>`).join("");
  el.innerHTML = key === "tidegate" && hotspots.length === 0
    ? base
    : `<svg ${VB}>${SCENES[key] || SCENES.tidegate}${markers}</svg>`;
  el.querySelectorAll(".hs-marker").forEach((node) => {
    node.addEventListener("click", () => onHotspot?.(node.dataset.hotspot));
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
