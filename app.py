"""Streamlit dashboard for the TCP congestion-control simulator."""

import matplotlib.pyplot as plt
import streamlit as st

from ai_narrator import AINarrator
from causal_agent import CausalDiagnosticAgent
from congestion_sim import CongestionSimulator


st.set_page_config(
    page_title="TCP Congestion Lab",
    page_icon="~",
    layout="wide",
    initial_sidebar_state="expanded",
)


def run_simulation(algorithm, rounds, capacity, buffer_size, loss_jitter):
    history = CongestionSimulator(
        algorithm=algorithm,
        rounds=rounds,
        capacity=capacity,
        buffer_size=buffer_size,
        loss_jitter=loss_jitter,
    ).run()
    diagnoses = CausalDiagnosticAgent(history, algorithm)
    diagnosis_rows = diagnoses.diagnose()
    return history, diagnosis_rows, diagnoses.summary()


def render_cwnd_chart(tahoe_history, reno_history):
    figure, axis = plt.subplots(figsize=(12, 4.5))
    axis.plot(
        [record.round_num for record in tahoe_history],
        [record.cwnd for record in tahoe_history],
        color="#e76f51",
        linewidth=2,
        label="Tahoe",
    )
    axis.plot(
        [record.round_num for record in reno_history],
        [record.cwnd for record in reno_history],
        color="#2a9d8f",
        linewidth=2,
        label="Reno",
    )
    axis.set_title("Congestion window response")
    axis.set_xlabel("Round (~1 RTT)")
    axis.set_ylabel("cwnd (packets)")
    axis.grid(alpha=0.2)
    axis.legend(frameon=False)
    figure.tight_layout()
    st.pyplot(figure, use_container_width=True)
    plt.close(figure)


def render_queue_rtt_chart(history):
    figure, (queue_axis, rtt_axis) = plt.subplots(1, 2, figsize=(12, 3.8))
    rounds = [record.round_num for record in history]
    queue_axis.plot(rounds, [record.queue_len for record in history], color="#457b9d", linewidth=2)
    queue_axis.set_title("Router queue")
    queue_axis.set_xlabel("Round")
    queue_axis.set_ylabel("Packets")
    queue_axis.grid(alpha=0.2)
    rtt_axis.plot(rounds, [record.avg_rtt for record in history], color="#f4a261", linewidth=2)
    rtt_axis.set_title("Average RTT")
    rtt_axis.set_xlabel("Round")
    rtt_axis.set_ylabel("Seconds")
    rtt_axis.grid(alpha=0.2)
    figure.tight_layout()
    st.pyplot(figure, use_container_width=True)
    plt.close(figure)


def render_diagnostics(history, diagnoses, widget_key):
    st.subheader("Round diagnostics")
    options = ["All rounds"] + [
        f"Round {diagnosis['round']} · {diagnosis['status']}"
        for diagnosis in diagnoses
        if diagnosis["status"] == "NOT GOOD"
    ]
    selected = st.selectbox("Inspect a round", options, key=widget_key)

    if selected == "All rounds":
        rows = [
            {
                "Round": diagnosis["round"],
                "Status": diagnosis["status"],
                "cwnd": round(diagnosis["cwnd"], 2),
                "Queue": round(diagnosis["queue"], 2),
                "Avg RTT": round(diagnosis["avg_rtt"], 3),
            }
            for diagnosis in diagnoses
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
        return

    round_number = int(selected.split()[1])
    diagnosis = next(item for item in diagnoses if item["round"] == round_number)
    record = history[round_number - 1]
    left, right = st.columns(2)
    left.metric("Event", record.event.replace("_", " ").title())
    right.metric("Packets dropped", record.num_dropped)
    st.caption(
        f"Round {round_number}: {record.num_sent} packets sent · "
        f"cwnd {record.cwnd:.1f} · queue {record.queue_len:.1f}/{record.buffer_size}"
    )
    for issue in diagnosis["issues"]:
        st.markdown(f"**{issue['type'].replace('_', ' ').title()}**")
        st.write(issue["symptom"])
        st.write(f"**Mechanism:** {issue['mechanism']}")
        st.write(f"**Root cause:** {issue['root_cause']}")
        if "algorithm_response" in issue:
            st.write(f"**Response:** {issue['algorithm_response']}")
        if "tradeoff" in issue:
            st.info(issue["tradeoff"])


st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; padding-bottom: 3rem;}
    [data-testid="stMetricValue"] {font-size: 1.8rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("TCP Congestion Lab")
st.write("Simulate AIMD behavior, compare Tahoe with Reno, and follow each congestion signal back to its cause.")

with st.sidebar:
    st.header("Experiment")
    rounds = st.slider("Rounds", 10, 150, 60)
    capacity = st.slider("Link capacity (packets / round)", 5, 60, 20)
    buffer_size = st.slider("Router buffer (packets)", 0, 60, 15)
    loss_jitter = st.slider("Random link loss", 0.0, 0.2, 0.0, 0.01)
    run_button = st.button("Run simulation", type="primary", use_container_width=True)

if run_button or "run" not in st.session_state:
    with st.spinner("Running Tahoe and Reno..."):
        tahoe = run_simulation("tahoe", rounds, capacity, buffer_size, loss_jitter)
        reno = run_simulation("reno", rounds, capacity, buffer_size, loss_jitter)
    st.session_state.run = {
        "tahoe": tahoe,
        "reno": reno,
        "narrator": AINarrator(),
        "settings": (rounds, capacity, buffer_size, loss_jitter),
    }

run = st.session_state.run
tahoe_history, tahoe_diagnoses, tahoe_summary = run["tahoe"]
reno_history, reno_diagnoses, reno_summary = run["reno"]

st.caption(
    f"{run['settings'][0]} rounds · {run['settings'][1]} packets/round capacity · "
    f"{run['settings'][2]} packet buffer · {run['settings'][3]:.0%} random loss"
)

tab_overview, tab_tahoe, tab_reno, tab_ask = st.tabs(["Overview", "Tahoe", "Reno", "Ask the agent"])

with tab_overview:
    st.subheader("Run health")
    metric_columns = st.columns(4)
    metric_columns[0].metric("Tahoe health", f"{tahoe_summary['health_pct']}%")
    metric_columns[1].metric("Reno health", f"{reno_summary['health_pct']}%")
    metric_columns[2].metric("Tahoe loss rounds", tahoe_summary["loss_events"])
    metric_columns[3].metric("Reno loss rounds", reno_summary["loss_events"])
    render_cwnd_chart(tahoe_history, reno_history)
    st.subheader("Queue and RTT")
    render_queue_rtt_chart(reno_history)

with tab_tahoe:
    st.subheader("Tahoe diagnosis")
    st.write(run["narrator"].narrate(tahoe_summary, tahoe_diagnoses))
    render_diagnostics(tahoe_history, tahoe_diagnoses, "tahoe_round_selector")

with tab_reno:
    st.subheader("Reno diagnosis")
    st.write(run["narrator"].narrate(reno_summary, reno_diagnoses))
    render_diagnostics(reno_history, reno_diagnoses, "reno_round_selector")

with tab_ask:
    st.subheader("Ask about this Reno run")
    question = st.text_input("Question", placeholder="Why did round 7 fail?")
    if question:
        st.write(run["narrator"].ask(question, reno_summary, reno_diagnoses))