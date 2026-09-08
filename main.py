"""
main.py
--------
Entry point. Runs Tahoe and Reno simulations, diagnoses each with the
CausalDiagnosticAgent, narrates the results, and saves all plots.

Usage:
    python main.py
    python main.py --rounds 80 --capacity 25 --buffer 10
    python main.py --interactive        # ask the AI agent follow-up questions
"""

import argparse
import json
import os

from congestion_sim import CongestionSimulator
from causal_agent import CausalDiagnosticAgent
from ai_narrator import AINarrator
from visualize import plot_sawtooth, plot_comparison, plot_queue_delay


def run_single(algorithm, rounds, capacity, buffer_size, loss_jitter, outdir):
    sim = CongestionSimulator(
        algorithm=algorithm, capacity=capacity, buffer_size=buffer_size,
        rounds=rounds, loss_jitter=loss_jitter,
    )
    history = sim.run()

    plot_sawtooth(
        history, title=f"{algorithm.title()} Congestion Window (Sawtooth)",
        save_path=os.path.join(outdir, f"{algorithm}_sawtooth.png"),
    )
    plot_queue_delay(history, save_path=os.path.join(outdir, f"{algorithm}_queue_delay.png"))

    agent = CausalDiagnosticAgent(history, algorithm)
    diagnoses = agent.diagnose()
    summary = agent.summary()

    narrator = AINarrator()
    narration = narrator.narrate(summary, diagnoses)

    print(f"\n=== {algorithm.upper()} Simulation Summary ===")
    print(json.dumps(summary, indent=2))
    print("\n--- AI Narration ---")
    print(narration)

    return history, diagnoses, summary, narrator


def main():
    parser = argparse.ArgumentParser(description="TCP Congestion Control Simulator + Causal Diagnostic Agent")
    parser.add_argument("--rounds", type=int, default=60)
    parser.add_argument("--capacity", type=int, default=20)
    parser.add_argument("--buffer", type=int, default=15)
    parser.add_argument("--loss-jitter", type=float, default=0.0, help="extra random link-noise loss prob, 0-1")
    parser.add_argument("--outdir", type=str, default="output")
    parser.add_argument("--interactive", action="store_true", help="ask the AI agent follow-up questions afterward")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    print("Running Tahoe simulation...")
    hist_tahoe, diag_tahoe, summ_tahoe, narrator_tahoe = run_single(
        "tahoe", args.rounds, args.capacity, args.buffer, args.loss_jitter, args.outdir
    )

    print("\nRunning Reno simulation...")
    hist_reno, diag_reno, summ_reno, narrator_reno = run_single(
        "reno", args.rounds, args.capacity, args.buffer, args.loss_jitter, args.outdir
    )

    plot_comparison(hist_tahoe, hist_reno, save_path=os.path.join(args.outdir, "tahoe_vs_reno.png"))

    print(f"\nAll plots saved to ./{args.outdir}/")

    if args.interactive:
        print("\nAsk the AI agent questions about the Reno run (empty line to quit):")
        while True:
            try:
                q = input("> ").strip()
            except EOFError:
                break
            if not q:
                break
            print(narrator_reno.ask(q, summ_reno, diag_reno))


if __name__ == "__main__":
    main()
