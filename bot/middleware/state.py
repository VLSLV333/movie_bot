from bot.integrations.graspil import GraspilForwarder


graspil_forwarder = GraspilForwarder(
    batch_window_s=60.0,
    max_batch=800,
    max_queue=5000,
    heartbeat_interval_s=3600.0,
)


