"""
congestion_sim.py
------------------
Layer 1: a round-based (1 round ~= 1 RTT) simulation of TCP's AIMD
(Additive-Increase / Multiplicative-Decrease) congestion control.

Model, in plain terms:
- Every round, the sender has `cwnd` packets "in flight".
- The bottleneck link can service `capacity` packets per round.
- Anything it can't service goes into a drop-tail queue (size `buffer_size`).
- If the queue is full, the overflow packets are DROPPED (packet loss).
- If the queue is not full but non-empty, packets still get through, but
  later -> extra queueing delay is added to their RTT (this is what causes
  a "delay" problem instead of a "loss" problem -- the bufferbloat effect).

Congestion control reaction (this is the actual textbook AIMD rule):
- On packet loss:
    ssthresh = max(2, cwnd / 2)
    Tahoe -> cwnd = 1                (full reset -> slow start again)
    Reno  -> cwnd = max(1, cwnd / 2) (fast recovery -> only halve)
- On success:
    if cwnd < ssthresh: cwnd *= 2    (slow start, exponential)
    else:                cwnd += 1   (congestion avoidance, linear)

This is the standard simplified AIMD sawtooth model used in networking
courses (e.g. Kurose & Ross), and it is *simulated*, not scripted: the
cwnd trace below is not values I typed in, it is Python computing them.
"""

import random
from dataclasses import dataclass, field


@dataclass
class Packet:
    round_num: int
    packet_id: int
    sent_time: float
    dropped: bool
    rtt: float = None  # None if the packet was dropped


@dataclass
class RoundRecord:
    round_num: int
    algorithm: str
    cwnd: float
    ssthresh: float
    queue_len: float
    capacity: int
    buffer_size: int
    num_sent: int
    num_dropped: int
    avg_rtt: float
    base_rtt: float
    event: str  # "slow_start" | "congestion_avoidance" | "loss_tahoe" | "loss_reno"
    packets: list = field(default_factory=list)


class CongestionSimulator:
    def __init__(
        self,
        algorithm: str = "reno",
        capacity: int = 20,       # bottleneck link capacity, packets/round
        buffer_size: int = 15,    # router queue capacity, packets
        base_rtt: float = 1.0,    # propagation-only RTT, seconds
        rounds: int = 60,
        loss_jitter: float = 0.0, # extra random per-packet loss prob (link noise)
        seed: int = 42,
    ):
        assert algorithm in ("tahoe", "reno"), "algorithm must be 'tahoe' or 'reno'"
        self.algorithm = algorithm
        self.capacity = capacity
        self.buffer_size = buffer_size
        self.base_rtt = base_rtt
        self.rounds = rounds
        self.loss_jitter = loss_jitter
        self.rng = random.Random(seed)

        self.cwnd = 1.0
        self.ssthresh = float(capacity * 2)  # initial guess, standard practice
        self.queue = 0.0
        self.history = []
        self._pid_counter = 0

    def _send_round(self, round_num):
        num_sent = max(1, int(round(self.cwnd)))
        packets = []

        incoming = self.queue + num_sent
        overflow = incoming - self.capacity  # what doesn't get serviced this round
        dropped_count = 0
        if overflow > self.buffer_size:
            dropped_count = min(num_sent, int(round(overflow - self.buffer_size)))

        for i in range(num_sent):
            self._pid_counter += 1
            is_dropped = i < dropped_count or self.rng.random() < self.loss_jitter
            queue_delay = self.queue / max(self.capacity, 1)
            rtt = None if is_dropped else self.base_rtt + queue_delay + self.rng.uniform(0, 0.02)
            packets.append(Packet(round_num, self._pid_counter, round_num * self.base_rtt, is_dropped, rtt))

        self.queue = max(0.0, min(overflow, self.buffer_size))
        return packets

    def run(self):
        self.history = []
        for r in range(1, self.rounds + 1):
            packets = self._send_round(r)
            num_dropped = sum(1 for p in packets if p.dropped)
            loss_detected = num_dropped > 0

            if loss_detected:
                self.ssthresh = max(2.0, self.cwnd / 2)
                if self.algorithm == "tahoe":
                    self.cwnd = 1.0
                    event = "loss_tahoe"
                else:
                    self.cwnd = max(1.0, self.cwnd / 2)
                    event = "loss_reno"
            else:
                if self.cwnd < self.ssthresh:
                    self.cwnd *= 2
                    event = "slow_start"
                else:
                    self.cwnd += 1
                    event = "congestion_avoidance"

            good_rtts = [p.rtt for p in packets if p.rtt is not None]
            avg_rtt = (
                sum(good_rtts) / len(good_rtts)
                if good_rtts
                else self.base_rtt + self.queue / max(self.capacity, 1)
            )

            self.history.append(
                RoundRecord(
                    round_num=r,
                    algorithm=self.algorithm,
                    cwnd=self.cwnd,
                    ssthresh=self.ssthresh,
                    queue_len=self.queue,
                    capacity=self.capacity,
                    buffer_size=self.buffer_size,
                    num_sent=len(packets),
                    num_dropped=num_dropped,
                    avg_rtt=avg_rtt,
                    base_rtt=self.base_rtt,
                    event=event,
                    packets=packets,
                )
            )
        return self.history


if __name__ == "__main__":
    # quick self-test
    sim = CongestionSimulator(algorithm="reno", rounds=20)
    for rec in sim.run():
        print(rec.round_num, rec.event, round(rec.cwnd, 2), rec.num_dropped)
