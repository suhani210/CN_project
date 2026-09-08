"""
causal_agent.py
----------------
Layer 2: the Causal Diagnostic Agent.

For every round of the simulation it checks two things per the brief:
    1. Did packets arrive safely?   (loss check)
    2. How long did they take?      (delay check)

If both are fine -> status = GOOD.
If not -> status = NOT GOOD, and the agent builds a causal chain:

    symptom  ->  mechanism  ->  root cause  ->  (algorithm's response)

instead of just slapping a label on it. It also explicitly names the
buffer-size trade-off: a bigger buffer means fewer drops (good for the
loss check) but longer queueing delay (bad for the delay check).
"""

DELAY_SPIKE_FACTOR = 1.5  # avg_rtt > factor * base_rtt counts as a delay problem


class CausalDiagnosticAgent:
    def __init__(self, history, algorithm_name):
        self.history = history
        self.algorithm_name = algorithm_name
        self.diagnoses = []

    # ---------- public API ----------

    def diagnose(self):
        self.diagnoses = []
        for rec in self.history:
            issues = []

            if rec.num_dropped > 0:
                issues.append(self._diagnose_loss(rec))

            # Only call it a "delay problem" if there wasn't already a loss
            # this round -- loss is the more urgent symptom and dominates.
            if rec.num_dropped == 0 and rec.avg_rtt > DELAY_SPIKE_FACTOR * rec.base_rtt:
                issues.append(self._diagnose_delay(rec))

            self.diagnoses.append(
                {
                    "round": rec.round_num,
                    "status": "GOOD" if not issues else "NOT GOOD",
                    "issues": issues,
                    "cwnd": rec.cwnd,
                    "queue": rec.queue_len,
                    "avg_rtt": rec.avg_rtt,
                }
            )
        return self.diagnoses

    def summary(self):
        total = len(self.diagnoses)
        bad = sum(1 for d in self.diagnoses if d["status"] == "NOT GOOD")
        loss_events = sum(1 for d in self.diagnoses for i in d["issues"] if i["type"] == "packet_loss")
        delay_events = sum(1 for d in self.diagnoses for i in d["issues"] if i["type"] == "delay_spike")
        return {
            "algorithm": self.algorithm_name,
            "total_rounds": total,
            "rounds_not_good": bad,
            "loss_events": loss_events,
            "delay_events": delay_events,
            "health_pct": round(100 * (total - bad) / total, 1) if total else 0.0,
        }

    # ---------- causal reasoning rules ----------

    def _diagnose_loss(self, rec):
        loss_rate = rec.num_dropped / rec.num_sent
        symptom = f"{rec.num_dropped} of {rec.num_sent} packets dropped this round ({loss_rate:.0%} loss)."
        mechanism = (
            f"cwnd had grown to {rec.cwnd:.1f} packets, but the bottleneck link only "
            f"drains {rec.capacity} pkts/round and its queue only holds {rec.buffer_size} "
            f"more -- so once the queue filled, the router (drop-tail) discarded the rest."
        )
        root_cause = (
            "Root cause: sending rate outran the bottleneck's capacity + buffer headroom. "
            "This is not a random link failure, it is the sender's own growth (slow start / "
            "congestion avoidance) pushing past what the network can currently absorb."
        )
        response = (
            f"{self.algorithm_name.title()} treats this loss as the congestion signal: "
            f"ssthresh is cut to cwnd/2"
            + (
                ", and cwnd is reset all the way to 1 (full slow-start restart)."
                if self.algorithm_name == "tahoe"
                else ", and cwnd is only halved (fast recovery), so it keeps more of its progress."
            )
        )
        return {
            "type": "packet_loss",
            "symptom": symptom,
            "mechanism": mechanism,
            "root_cause": root_cause,
            "algorithm_response": response,
        }

    def _diagnose_delay(self, rec):
        extra_delay = rec.avg_rtt - rec.base_rtt
        symptom = f"Average RTT rose to {rec.avg_rtt:.3f}s vs a base RTT of {rec.base_rtt:.3f}s."
        mechanism = (
            f"The queue is holding {rec.queue_len:.1f}/{rec.buffer_size} packets right now, "
            f"adding about {extra_delay:.3f}s of pure waiting time to every packet in flight."
        )
        root_cause = (
            "Root cause: the buffer is large enough to absorb the current burst instead of "
            "dropping it, so cwnd's growth shows up as queueing delay rather than as loss."
        )
        tradeoff = (
            "Buffer-size trade-off: a bigger buffer means fewer dropped packets (good for the "
            "loss check) but every packet waits longer in line (bad for the delay check) -- "
            "this is the classic 'bufferbloat' problem in real networks."
        )
        return {
            "type": "delay_spike",
            "symptom": symptom,
            "mechanism": mechanism,
            "root_cause": root_cause,
            "tradeoff": tradeoff,
        }


if __name__ == "__main__":
    from congestion_sim import CongestionSimulator

    sim = CongestionSimulator(algorithm="tahoe", rounds=30, capacity=15, buffer_size=8)
    hist = sim.run()
    agent = CausalDiagnosticAgent(hist, "tahoe")
    for d in agent.diagnose():
        if d["status"] == "NOT GOOD":
            print(f"Round {d['round']}: {d['status']}")
            for issue in d["issues"]:
                print("   ", issue["root_cause"])
    print(agent.summary())
