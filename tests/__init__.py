import os
import tempfile

# Must run before any `app` module is imported.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="thg-test-")
os.environ["TERMINAL_USER"] = "tester"
os.environ["TERMINAL_PASSWORD"] = "correct-horse-battery"
os.environ["SECRET_KEY"] = "k" * 40
