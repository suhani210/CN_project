"""
visualize.py
-------------
Turns a simulation history into the classic "sawtooth" plots.
Nothing here is hand-drawn -- every point comes straight out of
CongestionSimulator.run(), so the shape you see is the model's honest output.
"""

import matplotlib
matplotlib.use("Agg")  # safe for headless / non-GUI environments
import matplotlib.pyplot as plt


def plot_sawtooth(history, title="Congestion Window over Time", save_path=None):
    rounds = [r.round_num for r in history]
    cwnds = [r.cwnd for r in history]
    loss_rounds = [r.round_num for r in history if r.num_dropped > 0]
    loss_cwnds = [r.cwnd for r in history if r.num_dropped > 0]

    plt.figure(figsize=(10, 5))
    plt.plot(rounds, cwnds, label="cwnd", color="#2563eb", linewidth=1.6)
    plt.scatter(loss_rounds, loss_cwnds, color="#dc2626", zorder=5, label="loss event", s=28)
    plt.xlabel("Round (~1 RTT)")
    plt.ylabel("Congestion Window (packets)")
    plt.title(title)
    plt.legend()
    plt.grid(alpha=0.3)
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"Saved {save_path}")
    plt.close()


def plot_comparison(history_tahoe, history_reno, save_path=None):
    plt.figure(figsize=(10, 5))
    plt.plot(
        [r.round_num for r in history_tahoe], [r.cwnd for r in history_tahoe],
        label="Tahoe", color="#dc2626", linewidth=1.6,
    )
    plt.plot(
        [r.round_num for r in history_reno], [r.cwnd for r in history_reno],
        label="Reno", color="#16a34a", linewidth=1.6,
    )
    plt.xlabel("Round (~1 RTT)")
    plt.ylabel("Congestion Window (packets)")
    plt.title("Tahoe vs Reno: Congestion Window Comparison")
    plt.legend()
    plt.grid(alpha=0.3)
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"Saved {save_path}")
    plt.close()


def plot_queue_delay(history, save_path=None):
    rounds = [r.round_num for r in history]
    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.plot(rounds, [r.queue_len for r in history], color="#7c3aed", label="Queue length")
    ax1.set_xlabel("Round (~1 RTT)")
    ax1.set_ylabel("Queue length (packets)", color="#7c3aed")
    ax1.tick_params(axis="y", labelcolor="#7c3aed")

    ax2 = ax1.twinx()
    ax2.plot(rounds, [r.avg_rtt for r in history], color="#ea580c", label="Avg RTT")
    ax2.set_ylabel("Avg RTT (s)", color="#ea580c")
    ax2.tick_params(axis="y", labelcolor="#ea580c")

    plt.title("Queue Occupancy vs Delay (Bufferbloat view)")
    fig.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"Saved {save_path}")
    plt.close()
