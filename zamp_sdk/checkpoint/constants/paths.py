# Under the user's home, in ``~/.agent``: the platform keeps that folder writable in every sandbox mode (including
# versioned homes, where the home root and tracked folders are read-only) and it persists across re-runs.
CHECKPOINT_DIR_PARTS = (".agent", "checkpoints")
CHECKPOINT_FILE_PREFIX = ".zamp_checkpoint_"
