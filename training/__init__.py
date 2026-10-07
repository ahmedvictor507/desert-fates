"""Training scripts. Importing this package (every `python -m training.<script>` does) keeps
transformers and TRL away from optional integrations we don't use. Colab ships TensorFlow and
wandb builds that can be broken against its protobuf version, and both libraries import them
merely because they are installed."""
import os
import sys

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("WANDB_DISABLED", "true")
# A None entry makes importlib.util.find_spec("wandb") return None, so the libraries see wandb
# as not installed instead of importing it. Training logs go to the notebook (report_to="none").
sys.modules.setdefault("wandb", None)
