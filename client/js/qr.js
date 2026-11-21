// Saturday Multiverse — keyboard-wedge scanner listener.
// USB barcode/QR scanners emulate keyboards: a burst of characters
// followed by Enter. We detect the burst, treat it strictly as DATA,
// and hand it to the server allowlist. Nothing is ever eval'd here.

export function attachScanner(handler) {
  let buf = "";
  let last = 0;

  return (e) => {
    const now = Date.now();
    // typing faster than a human (~50ms/key) counts as a scanner burst
    const burst = now - last < 50;
    last = now;

    if (e.key === "Enter") {
      if (buf.length >= 8 && buf.startsWith("SM:")) {
        e.preventDefault();
        const payload = buf;
        buf = "";
        handler(payload);
        return;
      }
      buf = "";
      return;
    }
    if (e.key.length === 1) {
      buf = burst ? buf + e.key : e.key;
      if (buf.length > 300) buf = ""; // sanity cap
    } else if (e.key !== "Shift") {
      buf = ""; // any non-character key breaks a burst
    }
  };
}
