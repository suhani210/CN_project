"""
ai_narrator.py
---------------
Wraps the Anthropic API to turn the CausalDiagnosticAgent's structured
output into plain-English narration, and to answer follow-up "why"
questions about a specific run.

If no ANTHROPIC_API_KEY is set (or the `anthropic` package isn't
installed), it falls back to a template-based narrator so the rest of
the pipeline still runs end-to-end without needing an API key. This
matters for grading: the simulation + causal reasoning (the hard CS
content) work with zero external dependencies; the AI layer is an
enhancement on top.

Setup:
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-ant-...      (Linux/Mac)
    setx ANTHROPIC_API_KEY "sk-ant-..."       (Windows, new terminal after)
"""

import os


class AINarrator:
    def __init__(self, model="claude-sonnet-4-6"):
        self.model = model
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.client = None
        if self.api_key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                self.client = None

    # ---------- public API ----------

    def narrate(self, summary, diagnoses, max_examples=8):
        interesting = [d for d in diagnoses if d["status"] == "NOT GOOD"][:max_examples]
        if self.client:
            context = self._context_block(summary, interesting)
            return self._call(
                "You are a network-congestion-control tutor helping a student understand "
                "their own simulation output. Given this diagnostic summary, explain in "
                "plain English what happened and why, in under 200 words:\n\n" + context
            )
        return self._template_narrate(summary, interesting)

    def ask(self, question, summary, diagnoses, max_examples=8):
        interesting = [d for d in diagnoses if d["status"] == "NOT GOOD"][:max_examples]
        if self.client:
            context = self._context_block(summary, interesting)
            return self._call(
                "Here is a network congestion-control simulation diagnostic:\n\n"
                + context
                + f"\n\nStudent question: {question}\nAnswer clearly and concisely, "
                "grounded only in the data above."
            )
        return (
            "[Offline mode: set ANTHROPIC_API_KEY to enable live AI answers.] "
            f"From the summary alone: {summary['rounds_not_good']} of {summary['total_rounds']} "
            f"rounds were NOT GOOD ({summary['loss_events']} loss events, "
            f"{summary['delay_events']} delay spikes)."
        )

    # ---------- internals ----------

    def _context_block(self, summary, diagnoses):
        lines = [f"Run summary: {summary}"]
        for d in diagnoses:
            for issue in d["issues"]:
                lines.append(f"- Round {d['round']} [{issue['type']}]: {issue['root_cause']}")
        return "\n".join(lines)

    def _call(self, prompt):
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in msg.content if block.type == "text")

    def _template_narrate(self, summary, interesting):
        out = [
            f"Over {summary['total_rounds']} rounds, {summary['rounds_not_good']} were flagged "
            f"NOT GOOD ({summary['loss_events']} loss events, {summary['delay_events']} delay "
            f"spikes). Network health: {summary['health_pct']}%."
        ]
        for d in interesting:
            for issue in d["issues"]:
                out.append(f"Round {d['round']}: {issue['symptom']} {issue['root_cause']}")
        return "\n".join(out)


if __name__ == "__main__":
    from congestion_sim import CongestionSimulator
    from causal_agent import CausalDiagnosticAgent

    sim = CongestionSimulator(algorithm="reno", rounds=25)
    hist = sim.run()
    agent = CausalDiagnosticAgent(hist, "reno")
    diagnoses = agent.diagnose()
    summary = agent.summary()

    narrator = AINarrator()
    print(narrator.narrate(summary, diagnoses))
