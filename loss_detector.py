"""
loss_detector.py
----------------
Packet-loss detection, with the formulas spelled out.

1. Router-side overflow forecast (drop-tail model)
   For a link with capacity C (pkts/round) and buffer B, holding Q packets
   after round t, and offered A_{t+1} packets next round (sum of the cwnds of
   every flow crossing it):

        overflow_{t+1} = Q_t + A_{t+1} - C          (backlog after service)
        L_hat_{t+1}    = max(0, overflow_{t+1} - B) (packets that won't fit)

   A loss is *predicted* when L_hat >= 0.5 (rounds to at least one packet).
   After the round runs, the actual loss is split by cause:
        congestion loss  = what the overflow rule explains
        random loss      = observed loss the formula does NOT explain
                           (link noise / corruption)
   Forecast quality is scored with precision / recall against actual
   congestion events.

2. Sender-side loss-rate estimate (what a TCP endpoint can see)
        p_t = ALPHA * (lost_t / sent_t) + (1 - ALPHA) * p_{t-1}      (EWMA)
   and the steady-state window that loss rate supports (Mathis et al.):
        cwnd* = 1.22 / sqrt(p_t)
   If the flow's cwnd sits far above cwnd*, it is being too aggressive for the
   path and the next loss is likely.
"""

import math

ALPHA = 0.25
PREDICT_THRESHOLD = 0.5
FORMULAS = {
    "forecast": "L̂(t+1) = max(0, Q(t) + A(t+1) − C − B)",
    "classify": "congestion loss = min(drops, L̂); random loss = drops − congestion loss",
    "ewma": "p(t) = α·lost/sent + (1−α)·p(t−1),  α = 0.25",
    "mathis": "cwnd* = 1.22 / √p(t)",
}


def forecast_overflow(queue_after, offered_next, capacity, buffer_size):
    """L_hat: packets expected to be dropped next round at one link."""
    return max(0.0, queue_after + offered_next - capacity - buffer_size)


def flow_estimates(rounds):
    """Annotate a flow's per-round dicts with p_hat and the Mathis window."""
    p = 0.0
    for rec in rounds:
        inst = rec["dropped"] / rec["sent"] if rec["sent"] else 0.0
        p = ALPHA * inst + (1 - ALPHA) * p
        rec["loss_ewma"] = round(p, 4)
        rec["mathis_cwnd"] = round(1.22 / math.sqrt(p), 2) if p > 0 else None


def evaluate(link_log, link_names):
    """Score the forecast and classify losses. link_log entries carry
    queue/load/cong/noise/predicted per 'linkid:dir' per round."""
    per_link = {}
    rounds_out = []
    for r, links in enumerate(link_log, start=1):
        row = []
        for key, st in links.items():
            m = per_link.setdefault(
                key, {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "congestion": 0, "random": 0}
            )
            predicted = st["predicted"] >= PREDICT_THRESHOLD
            cong, noise = st["cong"], st["noise"]
            actual = cong > 0
            if predicted and actual:
                m["tp"] += 1
            elif predicted:
                m["fp"] += 1
            elif actual:
                m["fn"] += 1
            else:
                m["tn"] += 1
            m["congestion"] += cong
            m["random"] += noise
            if predicted or cong or noise:
                row.append(
                    {
                        "link": key,
                        "predicted": round(st["predicted"], 2),
                        "congestion": cong,
                        "random": noise,
                        "verdict": _verdict(predicted, cong, noise),
                    }
                )
        rounds_out.append(row)

    summary = []
    for key, m in per_link.items():
        tp, fp, fn = m["tp"], m["fp"], m["fn"]
        total = tp + fp + fn + m["tn"]
        summary.append(
            {
                "link": key,
                "name": link_names.get(key, key),
                "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                "recall": round(tp / (tp + fn), 3) if tp + fn else None,
                "accuracy": round((tp + m["tn"]) / total, 3) if total else None,
                "tp": tp, "fp": fp, "fn": fn,
                "congestion_drops": m["congestion"],
                "random_drops": m["random"],
            }
        )
    summary.sort(key=lambda s: -(s["congestion_drops"] + s["random_drops"]))
    return {"formulas": FORMULAS, "links": summary, "rounds": rounds_out}


def _verdict(predicted, cong, noise):
    if cong and noise:
        return "congestion + random loss"
    if cong:
        return "congestion loss (forecast hit)" if predicted else "congestion loss (missed by forecast)"
    if noise:
        return "random link loss (not explained by overflow)"
    return "false alarm" if predicted else "ok"
