// hyperresearch stop-gate — installed by `hyperresearch install --target omp`.
// Keeps this OMP session on the research pipeline while the newest run is
// mid-pipeline. Delete this file to uninstall. HYPERRESEARCH_STOP_GATE=0 disables.
export default function (pi) {
  pi.on("session_stop", async (event) => {
    if (event && event.stop_hook_active) return;
    try {
      const r = await pi.exec("{hpr_path}", ["run", "stop-gate", "--platform", "omp"], { timeout: 10000 });
      const raw = (r.stdout || "").trim();
      if (!raw) return; // gate allows the stop
      const decision = JSON.parse(raw);
      if (decision && decision.decision === "block" && decision.reason) {
        return { continue: true, additionalContext: String(decision.reason) };
      }
    } catch { /* a broken gate must not wedge the agent */ }
    return;
  });
}
