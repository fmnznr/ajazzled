// WebHID-Logger: in der Chrome-DevTools-Konsole der Treiber-Seite einfügen
// (am besten VOR dem Klick auf "Verbinden"). Loggt alle Reports in beide
// Richtungen, sendet selbst nichts.
//   __hidmark("text")  Markierung setzen (z.B. vor jedem Klick)
//   __hidsave()        Log als JSON herunterladen
//   copy(JSON.stringify(__hidlog))   Alternative: in die Zwischenablage
(() => {
  if (window.__hidlog) { console.log("HID-Logger läuft schon,", __hidlog.length, "Einträge"); return; }
  if (!window.HIDDevice) { console.error("Kein WebHID in diesem Kontext – oben in der Konsole den richtigen Frame wählen."); return; }
  const log = (window.__hidlog = []);
  const t0 = performance.now();
  const hex = (d) => {
    const u = d instanceof ArrayBuffer ? new Uint8Array(d) : new Uint8Array(d.buffer, d.byteOffset, d.byteLength);
    return Array.from(u, (b) => b.toString(16).padStart(2, "0")).join(" ");
  };
  const add = (dir, dev, rid, data, extra) => {
    const e = { t: Math.round(performance.now() - t0), dir, rid, len: data ? data.byteLength : 0, data: data ? hex(data) : "", ...extra };
    if (dev) e.dev = dev.vendorId.toString(16) + ":" + dev.productId.toString(16);
    log.push(e);
    console.log(`%c${dir}`, `color:${dir === "IN" ? "seagreen" : "royalblue"}`, "id=" + rid, e.data, extra || "");
  };
  const seen = new WeakSet();
  const attach = (dev) => {
    if (seen.has(dev)) return;
    seen.add(dev);
    log.push({ t: Math.round(performance.now() - t0), dir: "DEVICE", product: dev.productName,
      dev: dev.vendorId.toString(16) + ":" + dev.productId.toString(16),
      collections: dev.collections.map((c) => ({ usagePage: c.usagePage, usage: c.usage,
        out: c.outputReports.map((r) => r.reportId), in: c.inputReports.map((r) => r.reportId),
        feature: c.featureReports.map((r) => r.reportId) })) });
    dev.addEventListener("inputreport", (ev) => add("IN", dev, ev.reportId, ev.data));
  };
  const P = HIDDevice.prototype;
  const { open, sendReport, sendFeatureReport, receiveFeatureReport } = P;
  P.open = function () { attach(this); return open.apply(this, arguments); };
  P.sendReport = function (rid, data) { attach(this); add("OUT", this, rid, data); return sendReport.apply(this, arguments); };
  P.sendFeatureReport = function (rid, data) { attach(this); add("OUT_FEATURE", this, rid, data); return sendFeatureReport.apply(this, arguments); };
  P.receiveFeatureReport = async function (rid) {
    attach(this);
    const d = await receiveFeatureReport.apply(this, arguments);
    add("IN_FEATURE", this, rid, d);
    return d;
  };
  navigator.hid.getDevices().then((ds) => ds.forEach(attach));
  window.__hidmark = (label) => { log.push({ t: Math.round(performance.now() - t0), dir: "MARK", label }); console.log("%cMARK " + label, "color:orange"); };
  window.__hidsave = (name = "ak820-capture.json") => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(log, null, 1)], { type: "application/json" }));
    a.download = name;
    a.click();
  };
  console.log("HID-Logger aktiv. __hidmark('…') zum Markieren, __hidsave() zum Speichern.");
})();
