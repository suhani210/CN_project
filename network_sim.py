"""
network_sim.py
--------------
Topology-aware version of congestion_sim.py.

Instead of one hard-coded bottleneck, the network is a graph the user draws
(hosts / servers / routers / switches joined by links). Every link has its own
capacity (pkts/round), drop-tail buffer and propagation delay. Each *flow*
(src host -> dst host, Tahoe or Reno) is routed over the lowest-delay path and
runs the same AIMD rules as congestion_sim.py, but now flows that share a link
compete for it, and the link that actually drops packets is identified.

Topology JSON:
    {"nodes": [{"id": "n1", "type": "host|server|router|switch", "name": "PC1"}],
     "links": [{"id": "l1", "a": "n1", "b": "n2",
                "capacity": 20, "buffer": 15, "delay": 10, "loss": 0.0}],
     "flows": [{"id": "f1", "src": "n1", "dst": "n5", "algorithm": "reno", "start": 1}]}

delay is one-way propagation in ms; loss is a random per-packet loss probability.
"""

import heapq
import random

from causal_agent import CausalDiagnosticAgent
from congestion_sim import RoundRecord
from loss_detector import evaluate, flow_estimates, forecast_overflow

ENDPOINTS = ("host", "server")


class TopologyError(ValueError):
    pass


def find_path(nodes, links, src, dst):
    """Lowest-delay path src -> dst. Only routers/switches may be transit nodes.
    Returns a list of (link, direction) hops, direction being 'ab' or 'ba'."""
    by_id = {n["id"]: n for n in nodes}
    if src not in by_id or dst not in by_id:
        raise TopologyError("flow endpoint is not in the topology")
    if src == dst:
        raise TopologyError("flow source and destination are the same device")
    adj = {n["id"]: [] for n in nodes}
    for lk in links:
        w = float(lk.get("delay", 10)) + 0.001  # tiny hop penalty breaks ties
        adj[lk["a"]].append((lk["b"], lk, "ab", w))
        adj[lk["b"]].append((lk["a"], lk, "ba", w))
    best = {src: 0.0}
    prev = {}
    heap = [(0.0, src)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > best.get(u, float("inf")):
            continue
        if u == dst:
            break
        if u != src and by_id[u]["type"] in ENDPOINTS:
            continue  # end systems do not forward traffic
        for v, lk, direction, w in adj[u]:
            nd = d + w
            if nd < best.get(v, float("inf")):
                best[v] = nd
                prev[v] = (u, lk, direction)
                heapq.heappush(heap, (nd, v))
    if dst not in prev:
        raise TopologyError(
            f"no route from {by_id[src]['name']} to {by_id[dst]['name']} -- are they connected?"
        )
    hops, cur = [], dst
    while cur != src:
        u, lk, direction = prev[cur]
        hops.append((lk, direction))
        cur = u
    hops.reverse()
    return hops


class _Flow:
    def __init__(self, spec, hops, names):
        self.id = spec["id"]
        self.src, self.dst = spec["src"], spec["dst"]
        self.algorithm = spec.get("algorithm", "reno")
        if self.algorithm not in ("tahoe", "reno"):
            raise TopologyError("algorithm must be 'tahoe' or 'reno'")
        self.start = max(1, int(spec.get("start", 1)))
        self.hops = hops
        self.label = f"{names[self.src]} -> {names[self.dst]} ({self.algorithm})"
        self.base_rtt = 2 * sum(float(lk.get("delay", 10)) for lk, _ in hops) / 1000.0
        # the narrowest link on the path is what the causal agent should reason about
        self.bottleneck = min((lk for lk, _ in hops), key=lambda lk: int(lk["capacity"]))
        self.cwnd = 1.0
        self.ssthresh = float(2 * int(self.bottleneck["capacity"]))
        self.records = []


def _split_drops(total, shares):
    """Largest-remainder split of `total` drops across {flow: packets}, capped per flow."""
    weight = sum(shares.values())
    if weight <= 0 or total <= 0:
        return {f: 0 for f in shares}
    exact = {f: total * s / weight for f, s in shares.items()}
    out = {f: min(int(exact[f]), shares[f]) for f in shares}
    left = total - sum(out.values())
    for f in sorted(shares, key=lambda f: exact[f] - int(exact[f]), reverse=True):
        if left <= 0:
            break
        if out[f] < shares[f]:
            out[f] += 1
            left -= 1
    return out


def simulate(topology, rounds=60, seed=42):
    nodes, links = topology.get("nodes", []), topology.get("links", [])
    flow_specs = topology.get("flows", [])
    names = {n["id"]: n["name"] for n in nodes}
    link_ids = {lk["id"] for lk in links}
    for lk in links:
        if lk["a"] not in names or lk["b"] not in names:
            raise TopologyError(f"link {lk['id']} references a missing device")
    if not flow_specs:
        raise TopologyError("add at least one traffic flow (source host -> destination)")
    rounds = max(1, min(int(rounds), 500))
    rng = random.Random(seed)

    flows = [_Flow(s, find_path(nodes, links, s["src"], s["dst"]), names) for s in flow_specs]
    tick = max(f.base_rtt for f in flows) or 0.1  # one round ~ the longest RTT
    queues = {}  # (link id, direction) -> packets queued
    for f in flows:
        for lk, d in f.hops:
            queues.setdefault((lk["id"], d), 0.0)

    forecast = {}  # (link id, dir) -> L_hat forecast made at the end of the previous round
    link_log = []  # per round: {"l1:ab": {"queue", "load", "dropped", "util"}}
    for r in range(1, rounds + 1):
        active = [f for f in flows if r >= f.start]
        sent = {f.id: max(1, int(round(f.cwnd))) for f in active}
        alive = dict(sent)  # packets of each flow still in the network
        drops = {f.id: 0 for f in active}
        drop_where = {f.id: {} for f in active}
        qdelay = {f.id: 0.0 for f in active}
        round_links = {}

        # process each directional link once, earliest hop first
        order = {}
        for f in active:
            for i, (lk, d) in enumerate(f.hops):
                key = (lk["id"], d)
                order[key] = min(order.get(key, i), i)
        lk_by_id = {lk["id"]: lk for lk in links}
        for key in sorted(order, key=lambda k: order[k]):
            lk = lk_by_id[key[0]]
            cap, buf = int(lk["capacity"]), int(lk["buffer"])
            users = [f for f in active if any((h[0]["id"], h[1]) == key for h in f.hops)]
            before = queues[key]
            for f in users:
                qdelay[f.id] += before / max(cap, 1) * tick
            arriving = {f.id: alive[f.id] for f in users}

            # random link noise first (corruption), then congestion
            noise = {f.id: 0 for f in users}
            p = float(lk.get("loss", 0) or 0)
            if p > 0:
                for f in users:
                    noise[f.id] = sum(1 for _ in range(arriving[f.id]) if rng.random() < p)
            surv = {f.id: arriving[f.id] - noise[f.id] for f in users}
            overflow = before + sum(surv.values()) - cap
            congestion = 0
            if overflow > buf:
                congestion = min(sum(surv.values()), int(round(overflow - buf)))
            cong = _split_drops(congestion, surv)
            queues[key] = max(0.0, min(overflow, buf))
            for f in users:
                lost = noise[f.id] + cong[f.id]
                alive[f.id] -= lost
                drops[f.id] += lost
                if lost:
                    drop_where[f.id][lk["id"]] = drop_where[f.id].get(lk["id"], 0) + lost
            load = sum(arriving.values())
            round_links[f"{key[0]}:{key[1]}"] = {
                "queue": queues[key],
                "load": load,
                "dropped": noise_total(noise) + congestion,
                "cong": congestion,
                "noise": noise_total(noise),
                "predicted": forecast.get(key, 0.0),
                "util": min(1.0, (load + before) / max(cap, 1)),
            }
        link_log.append(round_links)

        for f in flows:
            if f.id not in sent:
                continue
            n_sent, n_drop = sent[f.id], drops[f.id]
            if n_drop > 0:
                f.ssthresh = max(2.0, f.cwnd / 2)
                f.cwnd = 1.0 if f.algorithm == "tahoe" else max(1.0, f.cwnd / 2)
                event = f"loss_{f.algorithm}"
            elif f.cwnd < f.ssthresh:
                f.cwnd *= 2
                event = "slow_start"
            else:
                f.cwnd += 1
                event = "congestion_avoidance"
            f.records.append(
                RoundRecord(
                    round_num=r,
                    algorithm=f.algorithm,
                    cwnd=f.cwnd,
                    ssthresh=f.ssthresh,
                    queue_len=queues[(f.bottleneck["id"], _dir_of(f, f.bottleneck))],
                    capacity=int(f.bottleneck["capacity"]),
                    buffer_size=int(f.bottleneck["buffer"]),
                    num_sent=n_sent,
                    num_dropped=n_drop,
                    avg_rtt=f.base_rtt + qdelay[f.id],
                    base_rtt=f.base_rtt,
                    event=event,
                )
            )
            f.records[-1].drop_where = drop_where[f.id]

        # forecast next round's overflow from the queues left behind and the new cwnds
        forecast = {}
        for key in queues:
            lk = lk_by_id[key[0]]
            offered = sum(
                max(1, int(round(f.cwnd)))
                for f in flows
                if f.start <= r + 1 and any((h[0]["id"], h[1]) == key for h in f.hops)
            )
            forecast[key] = forecast_overflow(queues[key], offered, int(lk["capacity"]), int(lk["buffer"]))

    return _package(flows, link_log, links, names)


def noise_total(noise):
    return sum(noise.values())


def _dir_of(flow, link):
    return next(d for lk, d in flow.hops if lk["id"] == link["id"])


def _package(flows, link_log, links, names):
    out_flows = []
    for f in flows:
        agent = CausalDiagnosticAgent(f.records, f.algorithm)
        diag = agent.diagnose()
        rounds = []
        for rec, dg in zip(f.records, diag):
            culprit = ""
            if rec.num_dropped:
                lid = max(rec.drop_where, key=rec.drop_where.get)
                lk = next(l for l in links if l["id"] == lid)
                culprit = f"{names[lk['a']]} <-> {names[lk['b']]}"
            arriving, trace = rec.num_sent, []
            for lk, _ in f.hops:
                lost = rec.drop_where.get(lk["id"], 0)
                trace.append([lk["id"], arriving, lost])
                arriving -= lost
            rounds.append(
                {
                    "hops": trace,
                    "round": rec.round_num,
                    "cwnd": round(rec.cwnd, 2),
                    "ssthresh": round(rec.ssthresh, 2),
                    "sent": rec.num_sent,
                    "dropped": rec.num_dropped,
                    "rtt": round(rec.avg_rtt, 4),
                    "event": rec.event,
                    "status": dg["status"],
                    "drop_link": culprit,
                    "issues": dg["issues"],
                }
            )
        flow_estimates(rounds)
        out_flows.append(
            {
                "id": f.id,
                "label": f.label,
                "algorithm": f.algorithm,
                "path": [names[f.src]]
                + [names[lk["b"] if d == "ab" else lk["a"]] for lk, d in f.hops],
                "path_nodes": [f.src]
                + [lk["b"] if d == "ab" else lk["a"] for lk, d in f.hops],
                "path_links": [lk["id"] for lk, _ in f.hops],
                "bottleneck": f"{names[f.bottleneck['a']]} <-> {names[f.bottleneck['b']]}",
                "base_rtt": round(f.base_rtt, 4),
                "summary": agent.summary(),
                "rounds": rounds,
            }
        )
    link_names = {}
    for lk in links:
        for d, (x, y) in (("ab", (lk["a"], lk["b"])), ("ba", (lk["b"], lk["a"]))):
            link_names[f"{lk['id']}:{d}"] = f"{names[x]} -> {names[y]}"
    return {"flows": out_flows, "links": link_log, "detection": evaluate(link_log, link_names)}


if __name__ == "__main__":
    topo = {
        "nodes": [
            {"id": "a", "type": "host", "name": "PC1"},
            {"id": "b", "type": "host", "name": "PC2"},
            {"id": "r", "type": "router", "name": "R1"},
            {"id": "s", "type": "server", "name": "Srv"},
        ],
        "links": [
            {"id": "l1", "a": "a", "b": "r", "capacity": 40, "buffer": 20, "delay": 5},
            {"id": "l2", "a": "b", "b": "r", "capacity": 40, "buffer": 20, "delay": 5},
            {"id": "l3", "a": "r", "b": "s", "capacity": 20, "buffer": 10, "delay": 20},
        ],
        "flows": [
            {"id": "f1", "src": "a", "dst": "s", "algorithm": "reno"},
            {"id": "f2", "src": "b", "dst": "s", "algorithm": "tahoe"},
        ],
    }
    res = simulate(topo, rounds=30)
    for fl in res["flows"]:
        print(fl["label"], fl["path"], fl["summary"])
