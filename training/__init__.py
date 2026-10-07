"""Training scripts. Importing this package (every `python -m training.<script>` does) tells
transformers to ignore TensorFlow: Colab ships a TensorFlow that can be broken against its
protobuf version, and transformers would otherwise import it while loading models."""
import os

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
