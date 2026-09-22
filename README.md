# TCP Congestion Control Simulator + Causal Diagnostic Agent

Two layers, as specified:

1. **`congestion_sim.py`** — simulates TCP's AIMD congestion control (Tahoe & Reno),
   round by round, producing the real "sawtooth" cwnd trace and a per-packet log
   (sent/dropped, RTT).
2. **`causal_agent.py`** + **`ai_narrator.py`** — a diagnostic agent that watches
   that packet log, flags GOOD/NOT GOOD, and reasons from symptom → mechanism →
   root cause. `ai_narrator.py` turns that into plain-English text via Claude
   (optional — has an offline fallback so it always runs).

## 1. How to run it (step by step)

```bash
# 1. Open this folder (CN_project) in VS Code
code .

# 2. Create a virtual environment (recommended, avoids polluting system Python)
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the simulation (works with zero setup — no API key needed yet)
python main.py

# 5. Check the output/ folder for:
#    tahoe_sawtooth.png, reno_sawtooth.png       -> individual sawtooths + loss markers
#    tahoe_queue_delay.png, reno_queue_delay.png -> bufferbloat view (queue vs RTT)
#    tahoe_vs_reno.png                            -> the comparison plot

# 6. Launch the interactive dashboard
streamlit run app.py
```

Optional — turn on live AI narration instead of the offline template:
```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...      # get one from console.anthropic.com
python main.py --interactive             # lets you ask the agent follow-up "why" questions
```

Useful flags to explore the model (also useful for your report / demo):
```bash
python main.py --rounds 100 --capacity 30 --buffer 5    # small buffer -> more loss, less delay
python main.py --rounds 100 --capacity 30 --buffer 40   # big buffer -> less loss, more delay (bufferbloat)
python main.py --loss-jitter 0.01                        # add random link noise on top of congestion loss
```

## 2. What you need to finish the project

You already have the hard 70%: a correct, tested AIMD simulator with an honest
sawtooth, a Tahoe/Reno comparison, and a rule-based causal reasoning engine with
AI narration. What's genuinely left for full marks:

- [ ] **Report / writeup** — screenshot the 3 plots, and for each NOT GOOD round
  the agent flags, paste its causal chain (symptom → mechanism → root cause).
  Explain in your own words why Reno's teeth sit higher than Tahoe's.
- [x] **Parameter sensitivity section** — small-buffer, big-buffer and
  high-capacity runs are already captured under `output_smallbuffer/`,
  `output_bigbuffer/` and `output_highcapacity/`. Write up the loss-vs-delay
  trade-off the logs already show (e.g. Reno's health drops from 89% at
  baseline to 68% with a big buffer, purely from delay spikes) using the
  `_diagnose_delay` output as evidence.
- [ ] **(Stretch) simple UI** — a Streamlit or Flask front end that lets you type
  a "why did round 7 fail?" question and shows the AI's answer live. Not required
  for the 70% milestone, but easy to bolt on with `ai_narrator.ask()` since that
  logic is already written — see `main.py --interactive` for the CLI version you
  can lift straight into a web form. (`app.py` already ships this as a Streamlit
  "Ask the agent" tab.)
- [ ] **(Stretch) unit tests** — `tests/test_congestion_sim.py` asserting e.g.
  Tahoe's cwnd hits exactly 1.0 after a loss, Reno's never goes below cwnd/2, etc.
- [ ] Fill in `ANTHROPIC_API_KEY` and confirm the *live* AI narration (not just
  the offline template) works, since your professor will likely want to see the
  actual LLM reasoning, not just the fallback text.

## 3. Project structure

```
CN_project/
├── congestion_sim.py   # Layer 1: AIMD simulator (Tahoe & Reno), drop-tail queue
├── causal_agent.py     # Layer 2: rule-based causal diagnosis engine
├── ai_narrator.py       # Layer 2: Claude-powered plain-English narration + Q&A
├── visualize.py         # matplotlib plotting (sawtooth, comparison, queue/delay)
├── app.py                # Streamlit interactive dashboard
├── main.py               # CLI entry point, orchestrates everything
├── requirements.txt
├── output/               # baseline plots + log
├── output_smallbuffer/   # sensitivity run: small buffer
├── output_bigbuffer/     # sensitivity run: big buffer
└── output_highcapacity/  # sensitivity run: high capacity
```

## 4. How the simulation actually works (for your report)

Each "round" ≈ one RTT. The sender has `cwnd` packets in flight. The bottleneck
link can only service `capacity` packets/round; anything extra sits in a
`buffer_size`-packet drop-tail queue. If the queue is full, overflow packets
are **dropped** (loss). If it isn't full but non-empty, packets still get
through but arrive **later** (queueing delay — the bufferbloat effect).

Congestion reaction, textbook AIMD:
- **On loss:** `ssthresh = cwnd/2`. Tahoe resets `cwnd = 1` (panic). Reno sets
  `cwnd = cwnd/2` (fast recovery — keeps more progress).
- **On success:** exponential growth (`cwnd *= 2`) while in slow start
  (`cwnd < ssthresh`), then linear growth (`cwnd += 1`) in congestion avoidance.

Nothing about the sawtooth shape is scripted — it falls out of running this
loop, which is what makes it "honest" simulation rather than a drawn chart.

## 5. How the causal agent reasons (for your report)

For every round it checks two things, per the brief:
1. Did packets arrive safely? → if any dropped, symptom = loss.
2. How long did they take? → if avg RTT > 1.5× base RTT (and no loss that
   round), symptom = delay spike.

Each symptom is expanded into a chain: **symptom → mechanism → root cause**,
plus (for loss) how the algorithm responds, and (for delay) an explicit
statement of the buffer-size trade-off. See `causal_agent.py`'s
`_diagnose_loss` / `_diagnose_delay` for the exact logic — it's short and
readable, good to walk through live in a demo.
